# VC Prompt Runner

A terminal Python application that automates running VC-focused prompts through ChatGPT using Playwright browser automation.

## Features

- Runs a configurable list of prompts from a JSON file
- Filters prompts based on provided command-line variables
- Uses Playwright to interact with ChatGPT in a real browser
- Extracts responses with markdown formatting preserved
- Captures source URLs from responses
- Extracts numerical scores when prompts request them
- Outputs structured JSON with all results

## Installation

```bash
# Install dependencies
pip install -r requirements.txt

# Install Playwright browsers
playwright install chromium
```

## Usage

```bash
python vc_prompt_runner.py --companyField "quantum computing" --CompanyName "IonQ"
```

### Arguments

| Argument | Description |
|----------|-------------|
| `--companyField` | The industry/field (e.g., "quantum computing", "AI", "biotech") |
| `--CompanyName` | Name of the company to analyze |
| `--CompanyProblems` | Problems the company claims to solve |
| `--CompanyICP` | Company's Ideal Customer Profile |
| `--BuyersPersona` | Company's target buyer persona |
| `--prompts-file` | Path to prompts JSON file (default: prompts.json) |
| `--output-dir` | Output directory for results (default: current directory) |
| `--headless` | Run browser in headless mode (not recommended) |
| `--dry-run` | Show which prompts would run without executing |
| `--prompt-ids` | Only run specific prompt IDs |

### Examples

```bash
# Run all field-related prompts
python vc_prompt_runner.py --companyField "AI"

# Run company analysis
python vc_prompt_runner.py --companyField "quantum computing" --CompanyName "IonQ"

# Full analysis with all variables
python vc_prompt_runner.py \
  --companyField "quantum computing" \
  --CompanyName "IonQ" \
  --CompanyProblems "quantum computing scalability" \
  --CompanyICP "Fortune 500 enterprises" \
  --BuyersPersona "CTOs and R&D directors"

# Dry run to see which prompts would execute
python vc_prompt_runner.py --companyField "biotech" --CompanyName "Moderna" --dry-run

# Run specific prompts only
python vc_prompt_runner.py --companyField "AI" --prompt-ids field_definition top_companies
```

## Output Format

The application generates a JSON file named `{companyField}-{CompanyName}-{DATE}.json`:

```json
[
  {
    "prompt": "What is quantum computing?",
    "answer": "**Quantum computing** is a type of computation...",
    "sources": ["https://en.wikipedia.org/wiki/Quantum_computing"],
    "score": null
  },
  {
    "prompt": "Is IonQ innovative? Give a brutally honest score from 1 to 10...",
    "answer": "IonQ demonstrates strong innovation in the quantum computing space...",
    "sources": ["https://ionq.com", "https://example.com/article"],
    "score": 8
  }
]
```

## How It Works

1. The app loads prompts from `prompts.json`
2. Filters prompts based on which variables are provided
3. Opens a Chromium browser and navigates to ChatGPT
4. Waits for you to log in (if not already logged in)
5. For each prompt:
   - Starts a new chat
   - Submits the prompt with VC context
   - Waits for response to complete
   - Extracts markdown, sources, and scores
6. Saves all results to a JSON file

## Notes

- ChatGPT login is required - the app will pause and wait for you to log in
- Running in headless mode is not recommended as ChatGPT may detect automation
- The system prompt "You are a VC in the {companyField} field. Add sources to your answer." is prepended to each prompt
- Prompts that require variables you haven't provided will be automatically skipped
