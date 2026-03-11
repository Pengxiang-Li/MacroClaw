# MacroClaw

Advanced macroeconomic and geopolitical investment assistant built on the OpenClaw framework.

## Setup

```bash
cp .env.example .env
# Fill in ANTHROPIC_API_KEY (required) and optional API keys
pip install -e .
```

## Usage

```bash
macroclaw                          # Full market brief (default)
macroclaw analyse "OPEC impact"    # Custom query
macroclaw config-check             # Validate configuration
```
