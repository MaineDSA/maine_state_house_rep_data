[![CodeQL](https://github.com/MaineDSA/maine_state_house_rep_data/actions/workflows/codeql.yml/badge.svg)](https://github.com/MaineDSA/maine_state_house_rep_data/actions/workflows/codeql.yml)
[![Python checks](https://github.com/MaineDSA/maine_state_house_rep_data/actions/workflows/python.yml/badge.svg)](https://github.com/MaineDSA/maine_state_house_rep_data/actions/workflows/python.yml)
[![Coverage badge](https://raw.githubusercontent.com/MaineDSA/maine_state_house_rep_data/python-coverage-comment-action-data/badge.svg)](https://htmlpreview.github.io/?https://github.com/MaineDSA/maine_state_house_rep_data/blob/python-coverage-comment-action-data/htmlcov/index.html)
[![Update CSV](https://github.com/MaineDSA/maine_state_house_rep_data/actions/workflows/update-data.yml/badge.svg)](https://github.com/MaineDSA/maine_state_house_rep_data/actions/workflows/update-data.yml)

# maine_state_house_rep_data
Maine state house reps by district and town.

## How to Use

1. Clone the repository.

1. Open a terminal and navigate to the newly cloned directory.

1. Install maine_state_house_rep_data.

  ```
  uv pip install .
  ```

  or without uv...

  ```
  pip install .
  ```

1. Run maine_state_house_rep_data.

  ```
  uv run maine_state_house_rep_data
  ```

  or without uv...

  ```
  maine_state_house_rep_data
  ```

The program will begin running and display its progress. Upon completion, the program will output a `house_municipality_data.csv` file containing the data and will overwrite any existing files.
