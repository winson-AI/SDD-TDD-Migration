"""Decoded presentation times, screen-source corroboration, and exact model clips."""
from bisect import bisect_left
import re
import subprocess

from contracts import file_ref, require
from ios_evidence import check_recording, frame_range, interval, local_ref
from ...storage import output_path


def ffmpeg():
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


def timeline(video):
    result = subprocess.run([ffmpeg(), '-hide_banner', '-nostdin', '-xerror', '-i', str(video), '-an',
                             '-vf', 'showinfo=checksum=0', '-f', 'null', '-'],
                            check=True, capture_output=True, text=True, timeout=60)
    frames = [(float(pts), float(duration)) for pts, duration in re.findall(
        r'n:\s*\d+\s+pts:\s*-?\d+\s+pts_time:([\d.e+-]+)\s+duration:\s*\d+\s+duration_time:([\d.e+-]+)',
        result.stderr)]
    require(frames and all(a[0] < b[0] for a, b in zip(frames, frames[1:])), 'iOS movie has no ordered decoded frame timeline')
    origin = frames[0][0]
    return [(pts - origin, duration) for pts, duration in frames]


def capture_times(video, facts, stopped_at):
    frames = timeline(video)
    ending = frames[-1][0] + frames[-1][1]
    start = facts['started_at']
    if facts['backend'] == 'simctl':
        start = max(start, stopped_at - ending)
    # Do not credit a long held frame as live AVFoundation capture during a dropped-frame interval.
    live = .25 if facts['backend'] == 'avfoundation' else float('inf')
    # simctl captures display changes as variable-rate video. Its held frames are part of one continuous recording.
    gaps = ([(start + t + min(d or nxt - t, live), start + nxt) for (t, d), (nxt, _) in zip(frames, frames[1:])
             if nxt - t - min(d or nxt - t, live) > .005] if facts['backend'] == 'avfoundation' else [])
    return {'timeline_version': 1, 'frame_pts': [t for t, _ in frames], 'gaps': gaps, 'started_at': start,
            'ended_at': min(stopped_at, start + frames[-1][0] + min(frames[-1][1], live)), 'decoded_duration': ending}


def match_wda(video, facts, trace, output):
    """Corroborate index-based capture with two distinct, timely WDA screen states."""
    import cv2
    import numpy as np

    def normalized(image):
        return cv2.resize(image, (48, 64), interpolation=cv2.INTER_AREA).astype('float32')

    def difference(left, right):
        return float(np.quantile(np.abs(left - right).mean(axis=2), .90))

    started, times = facts['started_at'], facts['frame_pts']
    movie = cv2.VideoCapture(str(video))
    matches = []
    try:
        for row in trace['steps']:
            for phase in ('before', 'after'):
                if f'{phase}_device' not in row:
                    continue
                timestamp = row[f'{phase}_device']['captured_at']
                picture = row[f'{phase}_ref']
                image = cv2.imread(str(local_ref(picture, output)))
                require(image is not None, 'iOS WDA checkpoint screenshot is not decodable')
                wanted = normalized(image)
                at = timestamp - started
                indices = {bisect_left(times, at + shift) for shift in (-.30, -.15, 0, .15, .30)}
                best = None
                for idx in sorted(indices):
                    if idx >= len(times) or abs(times[idx] - at) > .35:
                        continue
                    if not movie.set(cv2.CAP_PROP_POS_FRAMES, idx):
                        continue
                    ok, frame = movie.read()
                    if (not ok or int(movie.get(cv2.CAP_PROP_POS_FRAMES)) != idx + 1
                            or abs((frame.shape[1] / frame.shape[0]) / (image.shape[1] / image.shape[0]) - 1) > .08):
                        continue
                    sample = normalized(frame)
                    score = difference(wanted, sample)
                    if score <= 24 and (best is None or score < best[0]):
                        best = (score, idx, sample)
                if best is None:
                    continue
                score, idx, sample = best
                anchor = {'screenshot_ref': picture, 'captured_at': timestamp, 'frame_index': idx}
                for prior, prior_screen, prior_frame, prior_score in matches:
                    if (prior['frame_index'] < idx and prior['captured_at'] < timestamp
                            and difference(wanted, prior_frame) > max(score, prior_score) + 10
                            and difference(prior_screen, sample) > max(score, prior_score) + 10):
                        return [prior, anchor]
                matches.append((anchor, wanted, sample, score))
    finally:
        movie.release()
    raise ValueError('iOS AVFoundation frames do not match two distinct WDA checkpoints')


def prepare_clip(capture_ref, trace, assertion, device, output, path):
    facts = check_recording(capture_ref, trace, device, output)
    begin, end = interval(trace, assertion)
    first, last = frame_range(facts, begin, end)
    source = local_ref(facts['video_ref'], output)
    clip = output_path(path)
    pts = facts['frame_pts']
    subprocess.run([ffmpeg(), '-hide_banner', '-nostdin', '-v', 'error', '-n', '-i', str(source), '-an', '-vf',
                    f'trim=start_frame={first}:end_frame={last + 1}', '-frames:v', str(last - first + 1),
                    '-fps_mode', 'passthrough', '-enc_time_base:v', 'demux', '-c:v', 'libx264', '-bf', '0',
                    '-preset', 'fast', '-crf', '23', '-pix_fmt', 'yuv420p', '-use_editlist', '0', str(clip)],
                   check=True, capture_output=True, timeout=60)
    encoded = timeline(clip)
    require(len(encoded) == last - first + 1 and all(abs(t - (original - pts[first])) <= .005
            for (t, _), original in zip(encoded, pts[first:last + 1])),
            'iOS model clip does not retain the frozen source frames')
    return {'assertion_id': assertion['assertion_id'], 'query_sha256': trace['query_sha256'], 'capture_ref': capture_ref,
            'interval': [begin, end], 'frame_range': [first, last], 'frame_count': len(encoded), 'clip_ref': file_ref(clip)}
