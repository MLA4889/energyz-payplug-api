import requests
from .config import settings

MONDAY_API_URL = "https://api.monday.com/v2"

def _query(query: str, variables: dict = None):
    headers = {"Authorization": settings.MONDAY_API_KEY}
    data = {"query": query, "variables": variables or {}}
    r = requests.post(MONDAY_API_URL, json=data, headers=headers)
    r.raise_for_status()
    return r.json()

def get_item_columns(item_id: int, column_ids: list[str]):
    q = """
    query ($item_id: Int!) {
        items(ids: [$item_id]) {
            column_values {
                id
                text
            }
        }
    }
    """
    res = _query(q, {"item_id": item_id})
    values = res["data"]["items"][0]["column_values"]
    return {v["id"]: v for v in values if v["id"] in column_ids}

def get_formula_display_value(item_id: int, column_id: str):
    q = """
    query ($item_id: Int!, $col: [String!]!) {
        items(ids: [$item_id]) {
            column_values(ids: $col) {
                text
            }
        }
    }
    """
    res = _query(q, {"item_id": item_id, "col": [column_id]})
    items = res["data"]["items"]
    return items[0]["column_values"][0]["text"] if items else ""

def set_link_in_column(item_id: int, board_id: int, column_id: str, url: str, text: str):
    q = """
    mutation ($item_id: Int!, $board_id: Int!, $col_id: String!, $val: JSON!) {
        change_column_value(item_id: $item_id, board_id: $board_id, column_id: $col_id, value: $val) {
            id
        }
    }
    """
    val = {"url": url, "text": text}
    _query(q, {"item_id": item_id, "board_id": board_id, "col_id": column_id, "val": val})

def set_status(item_id: int, board_id: int, column_id: str, label: str):
    q = """
    mutation ($item_id: Int!, $board_id: Int!, $col_id: String!, $val: String!) {
        change_simple_column_value(item_id: $item_id, board_id: $board_id, column_id: $col_id, value: $val)
    }
    """
    _query(q, {"item_id": item_id, "board_id": board_id, "col_id": column_id, "val": label})
