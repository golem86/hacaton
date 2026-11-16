"""
Захист анонімності: приховування малих груп.

Правило з умови хакатону: результати груп, менших за мінімальний розмір (k),
НЕ показуються. Інакше, наприклад, якщо в підрозділі 2 цивільні працівники,
по їхньому «середньому балу» легко здогадатися, хто що відповів.

Приховати лише малу групу НЕДОСТАТНЬО. Якщо відомий загальний підсумок
(або підсумок по категорії), то «прихована» група = підсумок − сума видимих.
Тому використовуємо ДОДАТКОВЕ (вторинне) приховування:
сума всіх прихованих груп у межах одного підсумку має бути або 0, або ≥ k.
Якщо це не так, приховуємо ще й найменшу видиму групу, доки умова не виконається.
Тоді з різниці можна дізнатися лише суму кількох груп (≥ k), а не розмір однієї.

ВАЖЛИВО: УСІ адреси API, що віддають результати по групах, мають пропускати
дані через ці функції — для кожного підсумку, який стає відомим користувачу.
"""


def hidden_flags(sizes: list[int], k: int, force_hidden: list[bool] | None = None) -> list[bool]:
    """
    Повертає для кожної групи True, якщо її треба приховати.
      0) force_hidden — групи, які треба приховати примусово (бо їх приховано в іншому зрізі);
      1) первинне приховування: група менша за k;
      2) вторинне: поки сума прихованих між 0 і k, приховуємо найменшу видиму.
    """
    forced = force_hidden or [False] * len(sizes)
    hidden = [size < k or f for size, f in zip(sizes, forced)]
    while 0 < sum(s for s, h in zip(sizes, hidden) if h) < k and not all(hidden):
        visible = [i for i, h in enumerate(hidden) if not h]
        hidden[min(visible, key=lambda i: sizes[i])] = True
    return hidden


def suppress_small_groups(groups: list[dict], k: int, size_key: str = "responses",
                          keep_keys: tuple[str, ...] = (),
                          force_hidden: list[bool] | None = None) -> list[dict]:
    """
    Приймає список груп ОДНОГО підсумку, напр.
    [{"category": "staff", "responses": 4, "avg": 3.1}, ...].

    Для кожної прихованої групи кількість і ВСІ показники замінюються на None;
    залишаються лише ключі, що описують групу (keep_keys), і hidden=True.

    Повертає новий список, вхідні дані не змінює.
    """
    flags = hidden_flags([g[size_key] for g in groups], k, force_hidden)
    result = []
    for group, hidden in zip(groups, flags):
        if hidden:
            row = {key: (group[key] if key in keep_keys else None) for key in group}
            row["hidden"] = True
        else:
            row = {**group, "hidden": False}
        result.append(row)
    return result
