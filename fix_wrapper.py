import re

# Read the wrapper.py file
with open('src/backstop/wrapper.py', 'r') as f:
    content = f.read()

# Fix 1: Remove max_retries=0 from compat.Client calls
content = re.sub(
    r'    return compat\.Client\(\s*transport=BackstopTransport\(state, underlying, compat=compat\),\s*timeout=_timeout_from\(base, compat\),\s*base_url=_base_url_from\(base\),\s*max_retries=0,\s*\)',
    r'    return compat.Client(\n        transport=BackstopTransport(state, underlying, compat=compat),\n        timeout=_timeout_from(base, compat),\n        base_url=_base_url_from(base),\n    )',
    content
)

content = re.sub(
    r'    return compat\.AsyncClient\(\s*transport=AsyncBackstopTransport\(state, underlying, compat=compat\),\s*timeout=_timeout_from\(base, compat\),\s*base_url=_base_url_from\(base\),\s*max_retries=0,\s*\)',
    r'    return compat.AsyncClient(\n        transport=AsyncBackstopTransport(state, underlying, compat=compat),\n        timeout=_timeout_from(base, compat),\n        base_url=_base_url_from(base),\n    )',
    content
)

# Fix 2: Update comments to reflect the correct location of max_retries
content = content.replace(
    '# OpenAI Client accepts max_retries, so we use it for Backstop\'s retry logic.',
    '# OpenAI Client accepts max_retries, so we use it for Backstop\'s retry logic.\n    # httpx/httpx2 Client does NOT accept max_retries, so we do not pass it here.'
)

content = content.replace(
    '# OpenAI AsyncClient accepts max_retries, so we use it for Backstop\'s retry logic.',
    '# OpenAI AsyncClient accepts max_retries, so we use it for Backstop\'s retry logic.\n    # httpx/httpx2 AsyncClient does NOT accept max_retries, so we do not pass it here.'
)

# Fix 3: Make the cloning functions more robust
# First, let's check the current _clone_openai_client function
print("=== Current _clone_openai_client ===")
with open('src/backstop/wrapper.py', 'r') as f:
    lines = f.readlines()
    in_clone = False
    for i, line in enumerate(lines):
        if 'def _clone_openai_client' in line:
            in_clone = True
            print(f"{i+1}: {line.rstrip()}")
        elif in_clone:
            print(f"{i+1}: {line.rstrip()}")
            if line.strip() and not line.startswith(' ') and not line.startswith('\t'):
                in_clone = False

