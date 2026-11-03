"""Small statistics helpers used by the PyCursor demo task."""


def mean(nums: list[float]) -> float:
    if not nums:
        return 0
    total = 0
    for number in nums:
        total += number
    return total / len(nums)


def median(nums: list[float]) -> float:
    if not nums:
        raise ValueError("median() requires at least one value")
    ordered = sorted(nums)
    midpoint = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[midpoint]
    return (ordered[midpoint - 1] + ordered[midpoint]) / 2

