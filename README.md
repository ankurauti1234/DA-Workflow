# DA-

something

DA-Workflow is a comprehensive data processing pipeline designed for cleaning, merging, and analyzing viewership data. The project is optimized for cross-platform usage and features centralized configuration management.

## Project Structure

- `for-panel/`: Scripts and data for initial panel data cleaning.
- `sessions/`: Multi-stage sessionization logic.
  - `fp/`: Channel member-level session processing.
  - `logo/`: End-to-end pipeline for household viewership.
  - `merging/`: Logic to consolidate multiple session outputs.
- `statement/`: Final data processing and rule application (e.g., channel clipping).
- `config/`: **(Centralized)** Credentials, environment variables (`.env`), and channel mapping JSONs.

## Setup

### Prerequisites
- Python 3.8+
- [python-dotenv](https://pypi.org/project/python-dotenv/): For managing environment variables.
- [pandas](https://pandas.pydata.org/): For data manipulation.
- [psycopg2](https://pypi.org/project/psycopg2/): For PostgreSQL database connectivity.

### Installation
```bash
pip install pandas python-dotenv psycopg2 pytz
```

## Configuration

The project uses a central `config/` directory at the root. You must set up the following files:

### 1. `.env`
Create a `.env` file in the `config/` folder with your credentials:
```env
DB_HOST=your_db_host
DB_PORT=5432
DB_NAME=your_db_name
DB_USER=your_user
DB_PASS=your_password
TZ_OFFSET=4
TZ_NAME=Asia/Yerevan
```

### 2. `channel_mapping.json`
Centralized JSON mapping for channels and genres. Ensure it contains `name_to_id`, `id_to_name`, and `name_to_genre` keys.

### 3. `.pem` Files
Any required security keys should be placed in the `config/` directory.

## Usage

Scripts can be run independently or as part of a sequence. Paths are dynamically resolved based on the script location:

1. **Clean Panel Data**: Run `python for-panel/data-cleaning.py`.
2. **Process Sessions**: Navigate to `sessions/` subfolders or run the relevant scripts.
3. **Final Clipping**: Run `python statement/channel-clipping.py`.

## Cross-Platform Support

All scripts use `pathlib` for path resolution, making them compatible with both **Windows** and **Ubuntu/Linux**.

---
*Developed for efficient Da-Workflow management.*
