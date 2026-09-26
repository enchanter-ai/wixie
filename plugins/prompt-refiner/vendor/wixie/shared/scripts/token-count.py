#!/usr/bin/env python3
"""Wixie Token Counter — estimate prompt token usage and context window fit.

Stdlib only. Reads model specs from models-registry.json (single source of truth).

Usage:
    echo "prompt text" | python token-count.py [--model MODEL]
    python token-count.py <file> [--model MODEL]
"""
import sys, re, json, os

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REGISTRY_PATH = os.path.join(SCRIPT_DIR, "..", "models-registry.json")

def load_registry():
    try:
        with open(REGISTRY_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        windows = {}
        for model_id, info in data.get("models", {}).items():
            windows[model_id] = info.get("context_window", 0)
            # Add short aliases (e.g., "claude-opus" for "claude-opus-4-6")
            family = info.get("family", "").lower().replace(" ", "-")
            name = info.get("display_name", "").lower().replace(" ", "-")
            for alias in [family, name]:
                if alias and alias not in windows:
                    windows[alias] = info.get("context_window", 0)
        return windows, data.get("last_updated", "unknown")
    except (FileNotFoundError, json.JSONDecodeError):
        return {}, "unknown"

def read_input():
    skip_next = False
    args = []
    for i, a in enumerate(sys.argv[1:]):
        if skip_next:
            skip_next = False
            continue
        if a == "--model":
            skip_next = True
            continue
        if not a.startswith("--"):
            args.append(a)
    if args:
        try:
            with open(args[0], "r", encoding="utf-8") as f:
                return f.read()
        except FileNotFoundError:
            print(f"Error: File not found: {args[0]}", file=sys.stderr)
            sys.exit(2)
    elif not sys.stdin.isatty():
        return sys.stdin.read()
    print("Usage: echo 'prompt' | python token-count.py [--model MODEL]", file=sys.stderr)
    print("       python token-count.py <file> [--model MODEL]", file=sys.stderr)
    sys.exit(2)

def get_model():
    for i, a in enumerate(sys.argv[1:], 1):
        if a == "--model" and i < len(sys.argv) - 1:
            return sys.argv[i + 1].lower()
    return None

def estimate_tokens(text):
    words = len(text.split())
    code_blocks = len(re.findall(r'```', text))
    xml_tags = len(re.findall(r'<\w+', text))
    markup_bonus = (code_blocks + xml_tags) * 2
    return int(words * 1.3 + markup_bonus)

def detect_model(text):
    tl = text.lower()
    if re.search(r'\b(claude|anthropic)\b|<(instructions|context|example)>', tl):
        return "claude-sonnet-4-6"
    if re.search(r'\b(gpt-4\.1|gpt-4o)\b', tl): return "gpt-4o"
    if re.search(r'\b(gpt-5)\b', tl): return "gpt-5"
    if re.search(r'\b(o1|o3|o4-mini)\b', tl): return "o3"
    if re.search(r'\b(gemini)\b', tl): return "gemini-2.5-pro"
    if re.search(r'\b(llama)\b', tl): return "llama-4"
    if re.search(r'\b(mistral|mixtral)\b', tl): return "mistral-large"
    return None

def bar(ratio, w=30):
    f = min(round(ratio * w), w)
    return "#" * f + "." * (w - f)

def main():
    text = read_input()
    if not text.strip():
        print("Error: Empty prompt.", file=sys.stderr)
        sys.exit(2)

    model_windows, registry_date = load_registry()
    model = get_model() or detect_model(text)
    tokens = estimate_tokens(text)
    words = len(text.split())
    chars = len(text)
    lines = text.count("\n") + 1

    print()
    print("=" * 50)
    print("  WIXIE TOKEN COUNT")
    print("=" * 50)
    print(f"  Registry:        {registry_date}")
    print()
    print(f"  Words:           {words:,}")
    print(f"  Characters:      {chars:,}")
    print(f"  Lines:           {lines:,}")
    print(f"  Est. Tokens:     ~{tokens:,}")
    print()

    if model:
        window = model_windows.get(model, None)
        if window:
            ratio = tokens / window
            pct = ratio * 100
            remaining = window - tokens
            print(f"  Target Model:    {model}")
            print(f"  Context Window:  {window:,} tokens")
            print(f"  Prompt Usage:    {pct:.1f}%  {bar(ratio)}")
            print(f"  Remaining:       ~{remaining:,} tokens for response")
            print()
            if pct > 80:
                print("  [!!] WARNING: Prompt uses >80% of context window.")
                print("       Consider shortening or using a larger-window model.")
            elif pct > 50:
                print("  [!]  NOTE: Prompt uses >50% of context window.")
                print("       May limit very long outputs.")
            else:
                print("  [OK] Prompt fits comfortably within context window.")
        else:
            print(f"  Target Model:    {model} (not in registry)")
            print("       Update models-registry.json to add this model.")
    else:
        print("  Target Model:    Not detected. Use --model to specify.")

    print()
    print("=" * 50)

if __name__ == "__main__":
    main()
