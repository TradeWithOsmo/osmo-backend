import lighter
for api_name in dir(lighter):
    if api_name.endswith('Api'):
        api_cls = getattr(lighter, api_name)
        methods = [m for m in dir(api_cls) if not m.startswith('_')]
        found = False
        for m in methods:
            if 'book' in m.lower() or 'market' in m.lower():
                print(f"** {api_name}.{m} **")
                found = True
        if found:
            print(f"- {api_name} has matching methods")
