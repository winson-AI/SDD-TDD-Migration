import os
import re
from typing import Dict, List, Optional, Any
from ..logger import logger


class SkillManager:
    """
    Manages Agent Skills following the Agent Skills specification.

    Each skill is a directory containing at minimum a SKILL.md file with:
    - YAML frontmatter (name, description, and optional fields)
    - Markdown body with skill instructions

    Directory structure:
        skills/
        ├── skill-name-1/
        │   └── SKILL.md
        ├── skill-name-2/
        │   ├── SKILL.md
        │   ├── scripts/
        │   ├── references/
        │   └── assets/
    """
    _instance = None

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super(SkillManager, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self.skills: Dict[str, Dict[str, Any]] = {}
        self._initialized = True

    def load_skills(self, skills_die):
        """Load all skills from the directory."""
        if not os.path.exists(skills_die):
            logger.warning(f"Skills directory not found: {skills_die}")
            return

        # Iterate through subdirectories (each is a skill)
        for item in os.listdir(skills_die):
            skill_path = os.path.join(skills_die, item)

            # Skip non-directories and hidden files
            if not os.path.isdir(skill_path) or item.startswith('.'):
                continue

            # Look for SKILL.md in the directory
            skill_file = os.path.join(skill_path, "SKILL.md")
            if os.path.exists(skill_file):
                try:
                    skill_data = self._parse_skill_file(skill_file)
                    if skill_data:
                        skill_name = skill_data['metadata']['name']
                        self.skills[skill_name] = skill_data
                        logger.debug(f"Loaded skill: {skill_name}")
                except Exception as e:
                    logger.error(f"Failed to load skill from {skill_path}: {e}")

        logger.info(f"Loaded {len(self.skills)} skills from {skills_die}")

    def _parse_skill_file(self, file_path: str) -> Optional[Dict[str, Any]]:
        """
        Parse a SKILL.md file with YAML frontmatter.

        Returns a dictionary with:
        - metadata: dict with name, description, and optional fields
        - content: str the markdown body (without frontmatter)
        - file_path: str path to the skill directory
        """
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()

        # Parse YAML frontmatter
        metadata, body = self._parse_frontmatter(content)

        if not metadata or 'name' not in metadata:
            logger.error(f"Invalid skill file (missing name in frontmatter): {file_path}")
            return None

        # Validate name format
        if not self._validate_skill_name(metadata['name']):
            logger.error(f"Invalid skill name format: {metadata['name']}")
            return None

        skill_dir = os.path.dirname(file_path)

        return {
            'metadata': metadata,
            'content': body,
            'file_path': skill_dir,
            'scripts_dir': os.path.join(skill_dir, 'scripts') if os.path.exists(
                os.path.join(skill_dir, 'scripts')) else None,
            'references_dir': os.path.join(skill_dir, 'references') if os.path.exists(
                os.path.join(skill_dir, 'references')) else None,
            'assets_dir': os.path.join(skill_dir, 'assets') if os.path.exists(
                os.path.join(skill_dir, 'assets')) else None,
        }

    def _parse_frontmatter(self, content: str) -> tuple[Optional[Dict[str, Any]], str]:
        """
        Parse YAML frontmatter from content.

        Frontmatter format:
        ---
        key: value
        ---
        body content...

        Returns:
        - metadata dict (or None if invalid)
        - body content string
        """
        content = content.strip()

        # Check if content starts with ---
        if not content.startswith('---'):
            logger.warning("Missing YAML frontmatter delimiter")
            return None, content

        # Find the closing ---
        lines = content.split('\n')
        end_index = -1

        for i, line in enumerate(lines[1:], start=1):
            if line.strip() == '---':
                end_index = i
                break

        if end_index == -1:
            logger.warning("Missing closing YAML frontmatter delimiter")
            return None, content

        # Extract YAML content
        yaml_lines = lines[1:end_index]
        yaml_content = '\n'.join(yaml_lines)

        # Parse YAML (simple parser for basic key-value pairs)
        metadata = self._parse_simple_yaml(yaml_content)

        # Extract body
        body_lines = lines[end_index + 1:]
        body = '\n'.join(body_lines).strip()

        return metadata, body

    def _parse_simple_yaml(self, yaml_content: str) -> Dict[str, Any]:
        """
        Parse simple YAML key-value pairs.

        Supports:
        - Simple key: value pairs
        - Quoted strings
        - Nested mapping (metadata:)
        """
        metadata = {}
        current_key = None

        for line in yaml_content.split('\n'):
            # Skip empty lines and comments
            if not line.strip() or line.strip().startswith('#'):
                continue

            # Check indentation for nested values
            indent = len(line) - len(line.lstrip())
            stripped = line.strip()

            if indent == 0 and ':' in stripped:
                # Top-level key
                key, value = stripped.split(':', 1)
                key = key.strip()
                value = value.strip()

                if value:
                    # Simple key: value
                    metadata[key] = self._parse_yaml_value(value)
                else:
                    # Key with nested values (like metadata:)
                    current_key = key
                    metadata[key] = {}
            elif indent > 0 and current_key and ':' in stripped:
                # Nested key: value
                key, value = stripped.split(':', 1)
                metadata[current_key][key.strip()] = self._parse_yaml_value(value.strip())

        return metadata

    def _parse_yaml_value(self, value: str) -> str:
        """Parse a YAML value, handling quotes."""
        value = value.strip()

        # Remove surrounding quotes
        if (value.startswith('"') and value.endswith('"')) or \
                (value.startswith("'") and value.endswith("'")):
            value = value[1:-1]

        return value

    def _validate_skill_name(self, name: str) -> bool:
        """
        Validate skill name according to the specification.

        Rules:
        - 1-64 characters
        - Lowercase alphanumeric and hyphens only
        - Cannot start or end with hyphen
        - No consecutive hyphens
        """
        if not name or len(name) > 64:
            return False

        # Check for valid characters (lowercase alphanumeric and hyphens)
        if not re.match(r'^[a-z0-9-]+$', name):
            return False

        # Cannot start or end with hyphen
        if name.startswith('-') or name.endswith('-'):
            return False

        # No consecutive hyphens
        if '--' in name:
            return False

        return True

    def get_skill(self, skill_name: str) -> Optional[Dict[str, Any]]:
        """Get the full skill data including metadata and content."""
        return self.skills.get(skill_name)

    def get_skill_content(self, skill_name: str) -> Optional[str]:
        """Get the markdown body content of a skill."""
        skill = self.skills.get(skill_name)
        if skill:
            return skill['content']
        return None

    def get_skill_metadata(self, skill_name: str) -> Optional[Dict[str, Any]]:
        """Get the metadata of a specific skill."""
        skill = self.skills.get(skill_name)
        if skill:
            return skill['metadata']
        return None

    def get_all_skills_metadata(self) -> List[Dict[str, Any]]:
        """Return metadata of all available skills."""
        return [
            {
                'name': skill['metadata'].get('name', ''),
                'description': skill['metadata'].get('description', 'No description'),
                'license': skill['metadata'].get('license'),
                'compatibility': skill['metadata'].get('compatibility'),
            }
            for skill in self.skills.values()
        ]

    def get_skills_metadata(self) -> str:
        """Return formatted string of all available skills metadata."""
        metadata_list = []
        for skill in self.skills.values():
            name = skill['metadata'].get('name', 'Unknown')
            desc = skill['metadata'].get('description', 'No description')
            metadata_list.append(f"- {name}: {desc}")

        if not metadata_list:
            return "No skills available."

        return "\n".join(metadata_list)

    def list_skills(self) -> List[str]:
        """Return a list of all skill names."""
        return list(self.skills.keys())

    def get_script_path(self, skill_name: str, script_name: str) -> Optional[str]:
        """Get the full path to a script within a skill."""
        skill = self.skills.get(skill_name)
        if skill and skill['scripts_dir']:
            script_path = os.path.join(skill['scripts_dir'], script_name)
            if os.path.exists(script_path):
                return script_path
        return None

    def list_scripts(self, skill_name: str) -> List[str]:
        """List all script files available in a skill's scripts directory."""
        skill = self.skills.get(skill_name)
        if not skill or not skill['scripts_dir']:
            return []
        try:
            return sorted([
                f for f in os.listdir(skill['scripts_dir'])
                if os.path.isfile(os.path.join(skill['scripts_dir'], f))
            ])
        except Exception:
            return []

    def list_references(self, skill_name: str) -> List[str]:
        """List all reference files available in a skill's references directory."""
        skill = self.skills.get(skill_name)
        if not skill or not skill['references_dir']:
            return []
        try:
            return sorted([
                f for f in os.listdir(skill['references_dir'])
                if os.path.isfile(os.path.join(skill['references_dir'], f))
            ])
        except Exception:
            return []

    def get_reference_path(self, skill_name: str, reference_name: str) -> Optional[str]:
        """Get the full path to a reference file within a skill."""
        skill = self.skills.get(skill_name)
        if skill and skill['references_dir']:
            ref_path = os.path.join(skill['references_dir'], reference_name)
            if os.path.exists(ref_path):
                return ref_path
        return None

    def read_reference(self, skill_name: str, reference_name: str) -> Optional[str]:
        """Read the content of a reference file within a skill."""
        ref_path = self.get_reference_path(skill_name, reference_name)
        if ref_path and os.path.isfile(ref_path):
            try:
                with open(ref_path, "r", encoding="utf-8") as f:
                    return f.read()
            except Exception:
                return None
        return None

    def get_asset_path(self, skill_name: str, asset_name: str) -> Optional[str]:
        """Get the full path to an asset file within a skill."""
        skill = self.skills.get(skill_name)
        if skill and skill['assets_dir']:
            asset_path = os.path.join(skill['assets_dir'], asset_name)
            if os.path.exists(asset_path):
                return asset_path
        return None

    def get_skill_dir(self, skill_name: str) -> Optional[str]:
        """Get the root directory path of a skill."""
        skill = self.skills.get(skill_name)
        if skill:
            return skill.get('file_path')
        return None


if __name__ == '__main__':
    skill_manager = SkillManager()

    print("=" * 60)
    print("Available Skills:")
    print("=" * 60)
    print(skill_manager.get_skills_metadata())

    print("\n" + "=" * 60)
    print("Skills Metadata (structured):")
    print("=" * 60)
    for skill_meta in skill_manager.get_all_skills_metadata():
        print(f"\nName: {skill_meta['name']}")
        print(f"Description: {skill_meta['description']}")

    print("\n" + "=" * 60)
    print("Sample Skill Content:")
    print("=" * 60)
    # Try to get content for the first available skill
    skills_list = skill_manager.list_skills()
    if skills_list:
        first_skill = skills_list[0]
        print(f"\nContent for '{first_skill}':")
        print(skill_manager.get_skill_content(first_skill))
