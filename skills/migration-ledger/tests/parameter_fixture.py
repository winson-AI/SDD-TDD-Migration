"""A small legacy UI that states parameters in every way the sheet reads: layout XML, a style, a theme attribute, drawable layers and setters."""
from pathlib import Path
from types import SimpleNamespace

A = 'xmlns:android="http://schemas.android.com/apk/res/android"'
FILES = {
    'res/layout/home.xml': f'''<LinearLayout {A} xmlns:app="http://schemas.android.com/apk/res-auto"
    android:layout_width="match_parent" android:layout_height="wrap_content" android:orientation="vertical"
    android:padding="@dimen/gap" android:background="@drawable/bg_card">
  <TextView android:id="@+id/title" style="@style/Title" android:layout_width="wrap_content" android:layout_height="wrap_content"
      android:text="@string/home_title" android:textColor="?attr/inkColor" android:maxLines="2"/>
  <ImageView android:layout_width="24dp" android:layout_height="24dp" android:src="@drawable/ic_back" app:tint="@color/tint"
      android:contentDescription="Back" android:alpha="0.5"/>
</LinearLayout>''',
    'res/values/values.xml': '''<resources>
  <dimen name="gap">16dp</dimen><dimen name="title_size">18sp</dimen>
  <color name="brand">#3390EC</color><color name="ink">@color/brand</color>
  <string name="home_title">Home</string><string name="unused">Never shown</string>
  <style name="Title"><item name="android:textSize">@dimen/title_size</item><item name="android:textStyle">bold</item><item name="android:maxLines">1</item></style>
  <style name="AppTheme"><item name="inkColor">@color/ink</item></style>
</resources>''',
    'res/values-zh/values.xml': '<resources><string name="home_title">首页</string></resources>',
    'res/color/tint.xml': f'<selector {A}><item android:state_pressed="true" android:color="#FF0000"/><item android:color="@color/brand"/></selector>',
    'res/drawable/bg_card.xml': f'<shape {A} android:shape="rectangle"><solid android:color="@color/brand"/><corners android:radius="8dp"/>'
                                f'<stroke android:width="1dp" android:color="#22000000"/></shape>',
    'res/drawable/ic_back.xml': f'<vector {A} android:width="24dp" android:height="24dp" android:viewportWidth="24" android:viewportHeight="24">'
                                f'<path android:fillColor="#FF000000" android:pathData="M0,0h24v24h-24z"/></vector>',
    'java/demo/Home.kt': '''package demo
class Home {
    fun build() {
        title.setTextSize(TypedValue.COMPLEX_UNIT_DIP, 20f)
        title.setTextColor(Palette.color(Palette.ink))
        title.setPadding(dp(16), 0, dp(16), 0)
        title.setText(getString(R.string.home_title))
        title.setTypeface(Fonts.bold())
        title.setAlpha(if (visible) 1f else 0f)
        root.addView(title, Frames.frame(Frames.MATCH, 48, Gravity.TOP, 16, 0, 16, 0))
        badge.alpha = 0.8f
    }
    class Legacy { fun old() { footer.setTextSize(11f) } }
}
''',
}
HELPERS = [{'call': 'Frames.frame', 'params': ['layout_width', 'layout_height', 'layout_gravity', 'marginLeft', 'marginTop', 'marginRight', 'marginBottom'], 'unit': 'dp'}]


def build(root):
    """Write the legacy tree under `root` and return the collector arguments that index it."""
    for name, text in FILES.items():
        path = Path(root) / 'app/src/main' / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8')
    return SimpleNamespace(android_root=str(root), scope='home', entry=[], source_file=['Home.kt'], layout=['home'], layout_helpers=HELPERS)
