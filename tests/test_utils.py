import pytest
from app.utils import parse_item_and_quantity

@pytest.mark.asyncio
async def test_parse_item_and_quantity():
    # Test case 1: Item name only, default quantity
    parts = ["cmd", "凝血草"]
    item_name, quantity, error = parse_item_and_quantity(parts, default_quantity=1)
    assert item_name == "凝血草"
    assert quantity == 1
    assert error is None

    # Test case 2: Item name with quantity
    parts = ["cmd", "凝血草", "10"]
    item_name, quantity, error = parse_item_and_quantity(parts)
    assert item_name == "凝血草"
    assert quantity == 10
    assert error is None

    # Test case 3: Item name with spaces and quantity
    parts = ["cmd", "凝血草", "种子", "5"]
    item_name, quantity, error = parse_item_and_quantity(parts)
    assert item_name == "凝血草 种子"
    assert quantity == 5
    assert error is None
    
    # Test case 4: Item name with spaces, no quantity
    parts = ["cmd", "凝血草", "种子"]
    item_name, quantity, error = parse_item_and_quantity(parts)
    assert item_name == "凝血草 种子"
    assert quantity == 1
    assert error is None

    # Test case 5: Not enough parts
    parts = ["cmd"]
    item_name, quantity, error = parse_item_and_quantity(parts)
    assert item_name is None
    assert quantity is None
    assert error == "参数不足"

    # Test case 6: Invalid quantity (not a number at the end)
    parts = ["cmd", "Item", "zero"]
    item_name, quantity, error = parse_item_and_quantity(parts)
    assert item_name == "Item zero"
    assert quantity == 1
    assert error is None

    # Test case 7: Negative quantity
    parts = ["cmd", "Item", "-5"]
    item_name, quantity, error = parse_item_and_quantity(parts)
    assert item_name is None
    assert quantity is None
    assert error == "数量必须为正整数"
    
    # Test case 8: Zero quantity
    parts = ["cmd", "Item", "0"]
    item_name, quantity, error = parse_item_and_quantity(parts)
    assert item_name is None
    assert quantity is None
    assert error == "数量必须为正整数"
    
    # Test case 9: Empty item name
    parts = ["cmd", ""]
    item_name, quantity, error = parse_item_and_quantity(parts)
    assert item_name is None
    assert quantity is None
    assert error == "物品名称不能为空"
