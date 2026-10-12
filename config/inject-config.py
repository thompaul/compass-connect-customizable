import json
import argparse
import importlib.util
import sys
import re
from pathlib import Path
from typing import Dict, Any, NamedTuple, Optional, Iterable, Tuple


def _load_branding_assets():
    """
    The deployment's own module, loaded by path.

    What a document may be called, and which names a deployment will ever ask for, is decided
    in one place and used in two: here, for the env.js a developer runs against, and in
    `prepare_frontend.py`, for the one a deployment serves. Two copies of a naming convention
    is how a document ends up working on a laptop and invisible in production.

    By path rather than as `lib.branding_assets`, because that package's __init__ imports
    pulumi, which this script has no business requiring.
    """
    path = Path(__file__).resolve().parent.parent / 'iac' / 'lib' / 'branding_assets.py'
    spec = importlib.util.spec_from_file_location('branding_assets', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


DEFAULT_BACKEND_ENV_PATH = '../backend/.env'
DEFAULT_FRONTEND_ENV_PATH = '../frontend-new/public/data/env.js'

#: The shipped defaults, which a deployment's own file is layered on top of.
DEFAULT_DEFAULTS_PATH = Path(__file__).resolve().parent / 'default.json'

#: Where the deployment pipeline reads the variables it validates and uploads.
DEFAULT_ENV_TEMPLATE_PATH = Path(__file__).resolve().parent.parent / 'iac' / 'templates' / 'env.template'

class Derived(NamedTuple):
    """
    A variable computed from the configuration rather than copied out of it.

    Language is the reason this exists. It was configured twice, in two shapes: a list of
    locales for the two browser tiers, and a separate structured value carrying the default
    locale and per-locale date formats for the backend. Nothing compared them, so a locale
    could be offered in the menu and missing from the agent, which is exactly what happened.

    `namespace` is the top-level configuration key this is computed from, so `--namespaces`
    still selects it the way it selects a plain mapping.
    """
    namespace: str
    compute: Any


def _locales(config: Dict[str, Any]) -> list:
    """The deployment's declared locales, validated as a set before anything is derived."""
    i18n = config.get("i18n") or {}
    if "ui" in i18n or "conversation" in i18n:
        print("Error: the i18n namespace now declares locales once, as "
              "{'defaultLocale': ..., 'locales': [{'locale': ..., 'dateFormat': ...}]}.")
        print("       It used to be split into 'ui' and 'conversation', which could disagree "
              "- a locale offered in the menu that the agent could not converse in.")
        sys.exit(1)

    locales = i18n.get("locales") or []
    if not locales:
        return []

    names = []
    for entry in locales:
        if not isinstance(entry, dict) or not entry.get("locale"):
            print(f"Error: every entry in i18n.locales needs a 'locale'; got {entry!r}")
            sys.exit(1)
        names.append(entry["locale"])

    duplicates = {name for name in names if names.count(name) > 1}
    if duplicates:
        print(f"Error: i18n.locales lists {', '.join(sorted(duplicates))} more than once.")
        sys.exit(1)

    default = i18n.get("defaultLocale")
    if default and default not in names:
        print(f"Error: i18n.defaultLocale is '{default}', which is not in i18n.locales "
              f"({', '.join(names)}). A default nobody can select is not a default.")
        sys.exit(1)

    return locales


def derive_default_locale(config: Dict[str, Any]) -> Optional[str]:
    _locales(config)  # validated here too, so the error arrives however this is reached
    return (config.get("i18n") or {}).get("defaultLocale")


def derive_supported_locales(config: Dict[str, Any]) -> Optional[list]:
    locales = _locales(config)
    return [entry["locale"] for entry in locales] if locales else None


def derive_language_config(config: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    The backend's shape, built from the same declaration the menu is built from.

    Its date formats are the only thing here the browser tiers do not need, which is why
    this was a second setting rather than a second reading of the first one.
    """
    locales = _locales(config)
    if not locales:
        return None
    default = (config.get("i18n") or {}).get("defaultLocale")
    if not default:
        print("Error: i18n.defaultLocale is required when i18n.locales is set; the backend "
              "refuses to start without a default locale.")
        sys.exit(1)
    return {
        "default_locale": default,
        "available_locales": [
            {"locale": entry["locale"], "date_format": entry.get("dateFormat", "YYYY/MM/DD")}
            for entry in locales
        ],
    }


BACKEND_ENV_MAP: Dict[str, str] = {
    'GLOBAL_PRODUCT_NAME': 'branding.appName',

    # i18n - derived, so the menu and the agent cannot be told different things
    "BACKEND_LANGUAGE_CONFIG": Derived("i18n", derive_language_config),


    # Invitation Codes
    "GLOBAL_DISABLE_REGISTRATION_CODE": "auth.disableRegistrationCode",

    # CV Upload
    "GLOBAL_ENABLE_CV_UPLOAD": "cv.enabled",

    # Sector knowledge hub
    "GLOBAL_ENABLE_KNOWLEDGE_HUB": "knowledgeHub.enabled",

    # Add more backend env vars here
}

FRONTEND_ENV_MAP: Dict[str, str] = {
    'GLOBAL_PRODUCT_NAME': 'branding.appName',
    'GLOBAL_COUNTRY_NAME': 'branding.country',
    'FRONTEND_BROWSER_TAB_TITLE': 'branding.browserTabTitle',
    'FRONTEND_META_DESCRIPTION': 'branding.metaDescription',
    'FRONTEND_LOGO_URL': 'branding.assets.logo',
    'FRONTEND_DARK_LOGO_URL': 'branding.assets.darkLogo',
    'FRONTEND_FAVICON_URL': 'branding.assets.favicon',
    'FRONTEND_APP_ICON_URL': 'branding.assets.appIcon',
    'FRONTEND_CHAT_AVATAR_URL': 'branding.assets.chatAvatar',
    'FRONTEND_PARTNER_LOGOS': 'branding.partnerLogos',
    'FRONTEND_CONTACT_EMAIL': 'branding.contactEmail',
    'FRONTEND_FOOTER_ATTRIBUTION': 'branding.footerAttribution',
    'FRONTEND_FAQ_TUTORIAL_VIDEO_URL': 'faq.tutorialVideoUrl',
    'FRONTEND_ILLUSTRATIONS': 'branding.illustrations',
    'FRONTEND_THEME_CSS_VARIABLES': 'branding.theme',
    'FRONTEND_SEO': 'branding.seo',

    # Skills report
    "FRONTEND_SKILLS_REPORT_OUTPUT_CONFIG": "skillsReport",

    # Add more frontend env.js keys here

    # Invitation Codes
    "GLOBAL_DISABLE_LOGIN_CODE": "auth.disableLoginCode",
    "GLOBAL_DISABLE_REGISTRATION_CODE": "auth.disableRegistrationCode",
    "FRONTEND_DISABLE_REGISTRATION": "auth.disableRegistration",
    "FRONTEND_DISABLE_SOCIAL_AUTH": "auth.disableSocialAuth",

    # CV Upload
    "GLOBAL_ENABLE_CV_UPLOAD": "cv.enabled",

    # Sector knowledge hub
    "GLOBAL_ENABLE_KNOWLEDGE_HUB": "knowledgeHub.enabled",
    "FRONTEND_KNOWLEDGE_HUB_SECTORS": "knowledgeHub.sectors",

    # i18n - derived from the same declaration the backend's config is built from
    "FRONTEND_DEFAULT_LOCALE": Derived("i18n", derive_default_locale),
    "FRONTEND_SUPPORTED_LOCALES": Derived("i18n", derive_supported_locales),

    # Sensitive data Fields
    "FRONTEND_SENSITIVE_DATA_FIELDS": "sensitiveData.fields",

    # Analytics
    "FRONTEND_GTM_CONTAINER_ID": "analytics.gtmContainerId",
    "FRONTEND_GTM_ENABLED": "analytics.enabled",
}

FRONTEND_JSON_FIELDS = {
    'FRONTEND_THEME_CSS_VARIABLES',
    'FRONTEND_SEO',
    'FRONTEND_SKILLS_REPORT_OUTPUT_CONFIG',
    'FRONTEND_SUPPORTED_LOCALES',
    'FRONTEND_SENSITIVE_DATA_FIELDS',
    'FRONTEND_ILLUSTRATIONS',
    'FRONTEND_PARTNER_LOGOS',
    'FRONTEND_KNOWLEDGE_HUB_SECTORS',
    'FRONTEND_CONTENT_DOCUMENTS',
    # Add more JSON.stringify fields here
}


def deep_merge(base: Dict[str, Any], overlay: Dict[str, Any]) -> Dict[str, Any]:
    """
    Layer one configuration over another.

    Dictionaries merge key by key so a deployment's file carries only what differs from the
    shipped defaults - a theme with two colours changed is two colours, not thirty. Lists and
    scalars replace wholesale, because a partial list is never what anybody means. An explicit
    `null` deletes the key, which is the only way to say "not this one" about something the
    defaults provide.
    """
    merged = dict(base)
    for key, value in overlay.items():
        if value is None:
            merged.pop(key, None)
        elif isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def load_layered_config(defaults_path: Optional[Path], config_paths: Iterable[Path]) -> Dict[str, Any]:
    """
    The shipped defaults first, then each deployment file in the order given.

    Keeping the two apart is the point: the defaults can be updated with the product without
    overwriting anybody's choices, because nobody's choices are stored in them.
    """
    config: Dict[str, Any] = {}
    if defaults_path is not None:
        config = read_json(defaults_path)
    for path in config_paths:
        config = deep_merge(config, read_json(path))
    return config


def read_json(path: Path) -> Dict[str, Any]:
    try:
        return json.loads(path.read_text())
    except FileNotFoundError:
        print(f"Error: Config file not found at '{path}'")
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"Error: Invalid JSON in config file: {e}")
        sys.exit(1)


def get_by_dotted_path(obj: Any, dotted_path: str) -> Any:
    """Resolve a dotted path like 'branding.assets.logo' in a dict-like object."""
    current = obj
    for part in dotted_path.split('.'):
        if current is None:
            return None
        if isinstance(current, dict) and part in current:
            current = current[part]
        else:
            return None
    return current


def coerce_env_value(value: Any) -> Optional[str]:
    """Coerce values for .env writing."""
    if value is None:
        return None
    if isinstance(value, bool):
        # Backend env conventions vary; keep simple true/false
        return 'true' if value else 'false'
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        v = value.strip()
        return v if v != '' else None

    # For dict/list: store JSON (ensure_ascii=False preserves unicode characters like accented letters)
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)

    return str(value)


def build_env_updates(config: Dict[str, Any], mapping: Dict[str, str], namespaces: Optional[Iterable[str]] = None) -> Dict[str, Any]:
    """Build env var updates based on selected namespaces.

    If namespaces is provided, only mapping entries whose dotted-path starts with one of them are applied.
    """
    selected = set(namespaces) if namespaces else None

    updates: Dict[str, Any] = {}
    for env_key, source in mapping.items():
        if isinstance(source, Derived):
            if selected is not None and source.namespace not in selected:
                continue
            value = source.compute(config)
        else:
            if selected is not None and source.split('.', 1)[0] not in selected:
                continue
            value = get_by_dotted_path(config, source)
        if value is None:
            continue
        updates[env_key] = value
    return updates


def upsert_env_lines(lines: list[str], key: str, value: str) -> list[str]:
    """Upsert a KEY=VALUE line into .env content preserving other lines."""
    new_line = f"{key}={value}\n"
    out: list[str] = []
    found = False

    for line in lines:
        if not found and line.lstrip().startswith(f"{key}="):
            out.append(new_line)
            found = True
        else:
            out.append(line)

    if not found:
        if out and not out[-1].endswith('\n'):
            out[-1] += '\n'
        out.append(new_line)

    return out


def update_backend_env(config: Dict[str, Any], env_path: Path, namespaces: Optional[Iterable[str]] = None):
    if not env_path.exists():
        print(f"Error: Backend .env file not found at '{env_path}'")
        sys.exit(1)

    updates_raw = build_env_updates(config, BACKEND_ENV_MAP, namespaces)

    if not updates_raw:
        return

    lines = env_path.read_text().splitlines(keepends=True)

    for key, raw_value in updates_raw.items():
        value = coerce_env_value(raw_value)
        if value is None:
            continue
        lines = upsert_env_lines(lines, key, value)

    env_path.write_text(''.join(lines))


def extract_existing_frontend_json_value(content: str, key: str) -> Dict[str, Any]:
    """Extract the existing JSON.stringify payload for a key in env.js"""
    pattern = rf'(?:"{re.escape(key)}"|{re.escape(key)}):\s*btoa\(\s*JSON\.stringify\((.*?)\)\s*\),'
    match = re.search(pattern, content, re.DOTALL)
    if not match:
        return {}
    try:
        return json.loads(match.group(1).strip())
    except Exception:
        return {}


def insert_before_closing_brace(content: str, new_line: str) -> str:
    content = content.rstrip()
    if content.endswith('};'):
        return content[:-2] + new_line + '};\n'
    return content + new_line


def format_frontend_replacement(key: str, raw_value: Any, existing_content: str) -> Tuple[str, int]:
    """Return (replacement_string, regex_flags)."""
    if key in FRONTEND_JSON_FIELDS:
        # Merge dicts if possible so config can override but keep existing keys
        existing = extract_existing_frontend_json_value(existing_content, key)
        if isinstance(raw_value, dict) and isinstance(existing, dict):
            merged = {**existing, **raw_value}
        else:
            merged = raw_value

        formatted_json = json.dumps(merged, indent=2, ensure_ascii=False).replace('\n', '\n    ')
        return f'{key}: btoa(\n    JSON.stringify({formatted_json})\n  ),', re.DOTALL

    if isinstance(raw_value, bool):
        rendered = 'true' if raw_value else 'false'
    elif raw_value is None:
        rendered = ''
    else:
        rendered = str(raw_value)

    rendered = rendered.replace('\\', '\\\\').replace('"', '\\"')
    return f'{key}: btoa("{rendered}"),', 0


def local_content_documents(env_js_path: Path, config: Dict[str, Any]) -> list:
    """The documents a local run will serve, from `public/content/` beside the env.js."""
    branding_assets = _load_branding_assets()
    public_dir = env_js_path.parent.parent
    try:
        return branding_assets.content_documents(
            bundle_dir=str(public_dir),
            supported_locales=derive_supported_locales(config))
    except ValueError as refusal:
        print(f"Error: {refusal}")
        sys.exit(1)


def update_frontend_env(config: Dict[str, Any], env_js_path: Path, namespaces: Optional[Iterable[str]] = None):
    if not env_js_path.exists():
        print(f"Error: Frontend env.js file not found at '{env_js_path}'")
        sys.exit(1)

    content = env_js_path.read_text()

    updates = build_env_updates(config, FRONTEND_ENV_MAP, namespaces)

    # Not configured anywhere: worked out from the documents actually sitting in `public/`,
    # exactly as a deployment works it out from the documents it is about to upload. A
    # developer who drops their privacy policy in `public/content/` sees it, and a developer
    # who misnames it is told so here rather than three deployment steps later.
    if namespaces is None or 'i18n' in namespaces or 'branding' in namespaces:
        updates['FRONTEND_CONTENT_DOCUMENTS'] = local_content_documents(env_js_path, config)

    if not updates:
        return

    # Clean up multiple consecutive empty lines
    content = re.sub(r'\n\n+', '\n', content)

    for key, raw_value in updates.items():
        replacement, flags = format_frontend_replacement(key, raw_value, content)

        if key in FRONTEND_JSON_FIELDS:
            pattern = rf'(?:"{re.escape(key)}"|{re.escape(key)}):\s*btoa\(\s*JSON\.stringify\(.*?\)\s*\),'
        else:
            pattern = rf'(?:"{re.escape(key)}"|{re.escape(key)}):\s*btoa\([^)]+\),'

        if re.search(pattern, content, flags):
            content = re.sub(pattern, replacement, content, count=1, flags=flags)
        else:
            content = insert_before_closing_brace(content, f'  {replacement}\n')

    env_js_path.write_text(content)


#: Whitespace followed by `#` starts a comment in an env file, so a value carrying one is
#: silently truncated at that point - "Ranked #1 in the country" becomes "Ranked". Leading and
#: trailing whitespace is dropped for the same reason. Both are survivable by quoting.
NEEDS_QUOTING = re.compile(r'\s#')


def format_deployment_env_value(key: str, value: str) -> str:
    """
    Render a value so the env file gives it back unchanged.

    Worth the care: these values are a partner's free text and their JSON, and the failure
    mode is not an error but a quietly shorter string, three deployment steps downstream.
    """
    if '\n' in value or '\r' in value:
        print(f"Error: {key} contains a line break, which an environment file cannot carry.")
        sys.exit(1)

    if NEEDS_QUOTING.search(value) or value != value.strip():
        escaped = value.replace('\\', '\\\\').replace('"', '\\"')
        return f'"{escaped}"'
    return value


def deployment_env_map() -> Dict[str, str]:
    """
    Both tiers' variables, because the deployment keeps them in one file.

    `deploy_backend.py` reads the backend's from it and `prepare_frontend.py` reads the
    frontend's; which tier a variable belongs to is their business, not this file's. The two
    maps agree wherever they overlap, and this asserts it rather than letting one win quietly.
    """
    merged = dict(BACKEND_ENV_MAP)
    for key, dotted_path in FRONTEND_ENV_MAP.items():
        existing = merged.get(key)
        if existing is not None and existing != dotted_path:
            raise ValueError(
                f"{key} is mapped to '{existing}' for the backend and '{dotted_path}' for the "
                f"frontend. One variable cannot carry two different values into one env file.")
        merged[key] = dotted_path
    return merged


def template_variables(template_path: Path) -> set:
    """Every variable the deployment's validator knows about."""
    names = set()
    for line in template_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        names.add(line.split('=', 1)[0].strip())
    return names


def update_deployment_env(config: Dict[str, Any], env_path: Path, template_path: Optional[Path],
                          namespaces: Optional[Iterable[str]] = None):
    """
    Merge the configuration into the environment file the deployment pipeline consumes.

    This file also carries the infrastructure a deployment needs - database URIs, project ids,
    OAuth credentials - which are not customisation and are not in the configuration file. So
    this upserts rather than rewrites: lines it does not own are left exactly as they are.

    Unlike the local development writers, an empty value is written rather than skipped. The
    configuration file is meant to be this deployment's declared state, and skipping an empty
    would leave a previous value in place while the file said otherwise.
    """
    if not env_path.exists():
        print(f"Error: Deployment environment file not found at '{env_path}'")
        print("       Start from iac/templates/env.template and fill in the infrastructure "
              "values first; this merges your configuration into it.")
        sys.exit(1)

    updates_raw = build_env_updates(config, deployment_env_map(), namespaces)
    if not updates_raw:
        return

    if template_path is not None and template_path.exists():
        known = template_variables(template_path)
        unknown = sorted(key for key in updates_raw if key not in known)
        if unknown:
            print(f"Error: these would be written to '{env_path.name}' and the deployment "
                  f"does not know them: {', '.join(unknown)}")
            print("       A variable the template does not list reaches nothing. Add it to "
                  "iac/templates/env.template and to the tier that reads it.")
            sys.exit(1)

    lines = env_path.read_text().splitlines(keepends=True)
    for key, raw_value in updates_raw.items():
        lines = upsert_env_lines(lines, key, format_deployment_env_value(key, coerce_env_value(raw_value) or ''))

    env_path.write_text(''.join(lines))
    print(f"Wrote {len(updates_raw)} configuration values into {env_path}")


def parse_args(argv: Optional[list[str]] = None):
    parser = argparse.ArgumentParser(
        description='Turn a configuration file into the environment variables that carry it',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Two destinations.

  A deployment - merges into the file setup_env.py uploads, leaving the infrastructure
  values in it untouched:

    python3 inject-config.py --config my-deployment.json \
        --deployment-env /path/to/config-dir/.env.myrealm.prod

  Local development - the backend .env and the frontend's runtime env.js:

    python3 inject-config.py --config my-deployment.json
    python3 inject-config.py --config my-deployment.json --namespaces branding auth

Your file is layered over the shipped defaults, so it needs to carry only what differs.
Pass --no-defaults to use it alone, or --config more than once to layer several.
        """
    )

    parser.add_argument('--config', required=True, action='append', metavar='CONFIG_FILE',
                        help='Your configuration JSON. Repeat to layer several, last wins.')
    parser.add_argument('--defaults', default=str(DEFAULT_DEFAULTS_PATH), metavar='CONFIG_FILE',
                        help='The shipped defaults your file is layered over (default: config/default.json)')
    parser.add_argument('--no-defaults', dest='defaults', action='store_const', const=None,
                        help='Use the given file or files alone, with nothing underneath them')
    parser.add_argument('--deployment-env', default=None, metavar='ENV_FILE',
                        help='Merge into a deployment environment file (.env.<realm>.<env>) '
                             'instead of writing the local development files')
    parser.add_argument('--env-template', default=str(DEFAULT_ENV_TEMPLATE_PATH), metavar='TEMPLATE',
                        help='The template to check written variable names against '
                             '(default: iac/templates/env.template)')
    parser.add_argument('--backend-env', default=DEFAULT_BACKEND_ENV_PATH, help='Path to backend .env')
    parser.add_argument('--frontend-env', default=DEFAULT_FRONTEND_ENV_PATH, help='Path to frontend env.js')
    parser.add_argument('--namespaces', nargs='*', default=None,
                        help='Only apply these top-level namespaces (e.g., branding, auth). Omit to apply all mapped keys.')

    return parser.parse_args(argv)


def main():
    args = parse_args()

    config = load_layered_config(
        Path(args.defaults) if args.defaults else None,
        [Path(path) for path in args.config],
    )

    if args.deployment_env:
        update_deployment_env(
            config,
            Path(args.deployment_env),
            Path(args.env_template) if args.env_template else None,
            args.namespaces,
        )
    else:
        update_backend_env(config, Path(args.backend_env), args.namespaces)
        update_frontend_env(config, Path(args.frontend_env), args.namespaces)

    print('Configuration injected successfully')


if __name__ == '__main__':
    main()
