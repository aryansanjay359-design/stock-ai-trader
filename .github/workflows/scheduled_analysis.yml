name: Scheduled AI Stock Analysis

on:
  schedule:
    # Runs at 14:00, 15:30, and 17:00 UTC (= 2pm, 3:30pm, 5pm UK time BST)
    # Note: UK is UTC+1 in summer (BST), UTC+0 in winter (GMT)
    # These times cover the window you asked for
    - cron: '0 13 * * 1-5'    # 2:00pm UK (BST)
    - cron: '30 14 * * 1-5'   # 3:30pm UK (BST)
    - cron: '0 16 * * 1-5'    # 5:00pm UK (BST)

  # Lets you trigger it manually from GitHub too
  workflow_dispatch:

jobs:
  analyse:
    runs-on: ubuntu-latest

    steps:
      - name: Check out repo
        uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'

      - name: Install dependencies
        run: pip install requests

      - name: Run AI analysis and notify
        env:
          FINNHUB_KEY: ${{ secrets.FINNHUB_KEY }}
          GROQ_KEY:    ${{ secrets.GROQ_KEY }}
          NTFY_TOPIC:  ${{ secrets.NTFY_TOPIC }}
        run: python scheduled_analysis.py
