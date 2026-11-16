"""
Захист анонімності: приховування малих груп.

Правило з умови хакатону: результати груп, менших за мінімальний розмір (k),
НЕ показуються. Інакше, наприклад, якщо в підрозділі 2 цивільні працівники,
по їхньому «середньому балу» легко здогадатися, хто що відповів.

ВАЖЛИВО: УСІ адреси API, що віддають результати по групах
(будь-яке поєднання: категорія, підрозділ, категорія + підрозділ...),
мають пропускати дані через функцію suppress_small_groups.
"""


def suppress_small_groups(groups: list[dict], k: int, size_key: str = "responses",
                          keep_keys: tuple[str, ...] = ()) -> list[dict]:
    """
    Приймає список груп, напр. [{"category": "staff", "responses": 4, "avg": 3.1}, ...].

    Для кожної групи, де кількість відповідей < k:
      - кількість і ВСІ показники замінюються на None;
      - залишаються лише ключі, що описують групу (keep_keys), і hidden=True.

    Повертає новий список, вхідні дані не змінює.
    """
    result = []
    for group in groups:
        size = group[size_key]
        if size >= k:
            result.append({**group, "hidden": False})
        else:
            hidden = {key: (group[key] if key in keep_keys else None) for key in group}
            hidden["hidden"] = True
            result.append(hidden)
    return result
