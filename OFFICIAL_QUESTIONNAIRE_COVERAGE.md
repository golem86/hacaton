# Покриття офіційних анкет — Додаток В

Джерело: [Рекомендації НУОУ, Додаток В, друковані с. 53–66](https://nuou.org.ua/assets/documents/recommendations_transform_dobrochesnist.pdf). PDF звірено за нумерацією, розділами, початковими сторінками питань і кількістю варіантів. **Анкета 1: 12/12 питань; Анкета 2: 10/10 питань.** Формулювання `2.0.0` — власні стислі адаптації за змістом, позначені `wording: adapted`; це не дослівний офіційний текст. Джерело має описові варіанти `single_choice`; жодного score або weight в каталозі немає.

| Form | Section | Source page | Question № | Catalog ID | Version | Status |
| --- | --- | ---: | ---: | --- | --- | --- |
| 1 | 1 Культура | 53 | 1 | `av-f1-culture-1` | 2.0.0 | adapted, 5 options |
| 1 | 1 Культура | 53 | 2 | `av-f1-culture-2` | 2.0.0 | adapted, 5 options |
| 1 | 1 Культура | 54 | 3 | `av-f1-culture-3` | 2.0.0 | adapted, 5 options |
| 1 | 1 Культура | 54 | 4 | `av-f1-culture-4` | 2.0.0 | adapted, 5 options |
| 1 | 1 Культура | 55 | 5 | `av-f1-culture-5` | 2.0.0 | adapted, 5 options |
| 1 | 2 Система | 55 | 1 | `av-f1-system-1` | 2.0.0 | adapted, 5 options |
| 1 | 2 Система | 56 | 2 | `av-f1-system-2` | 2.0.0 | adapted, 5 options |
| 1 | 3 Підзвітність | 56 | 1 | `av-f1-accountability-1` | 2.0.0 | adapted, 5 options |
| 1 | 3 Підзвітність | 57 | 2 | `av-f1-accountability-2` | 2.0.0 | adapted, 5 options |
| 1 | 3 Підзвітність | 57 | 3 | `av-f1-accountability-3` | 2.0.0 | adapted, **6 options** |
| 1 | 3 Підзвітність | 58 | 4 | `av-f1-accountability-4` | 2.0.0 | adapted, 5 options |
| 1 | 4 Рівень зрілості | 58 | 1 | `av-f1-maturity-1` | 2.0.0 | adapted, 5 options |
| 2 | 1 Культура | 60 | 1 | `av-f2-culture-1` | 2.0.0 | adapted, 5 options |
| 2 | 1 Культура | 60 | 2 | `av-f2-culture-2` | 2.0.0 | adapted, 5 options |
| 2 | 1 Культура | 61 | 3 | `av-f2-culture-3` | 2.0.0 | adapted, 5 options |
| 2 | 2 Система | 61 | 1 | `av-f2-system-1` | 2.0.0 | adapted, 5 options |
| 2 | 2 Система | 62 | 2 | `av-f2-system-2` | 2.0.0 | adapted, 5 options |
| 2 | 3 Підзвітність | 62 | 1 | `av-f2-accountability-1` | 2.0.0 | adapted, 5 options |
| 2 | 3 Підзвітність | 63 | 2 | `av-f2-accountability-2` | 2.0.0 | adapted, 5 options |
| 2 | 3 Підзвітність | 63 | 3 | `av-f2-accountability-3` | 2.0.0 | adapted, **6 options** |
| 2 | 3 Підзвітність | 64 | 4 | `av-f2-accountability-4` | 2.0.0 | adapted, 5 options |
| 2 | 4 Рівень зрілості | 64 | 1 | `av-f2-maturity-1` | 2.0.0 | adapted, 5 options |

Початкова сторінка зазначена для кожного питання; варіанти деяких питань продовжуються на наступній сторінці. У друкованій Анкеті 1 питання 4 і 5 розділу «Культура» повторюють тему відкритості з однаковими за змістом варіантами. Каталог зберігає **обидва** номери та окремі ID без редакційного вилучення. У розділі «Підзвітність» питання 3 про викривачів має шість варіантів в обох формах, тоді як інші питання мають п’ять. Перевірено відсутність дублікатів ID у межах версії.

Історичні `1.0.0` (1+1 питання) і `1.1.0` (2+2 питання) збережені без редагування змісту. ID однакового питання може повторюватися між версіями того самого шаблону; ключ відповіді для майбутнього API має включати `template_id` і `version`. Після публікації об’єкти шаблонів, питань і варіантів заморожені в runtime.

**Аудиторія Анкети 2 не визначена автоматично:** заголовок на [с. 60](https://nuou.org.ua/assets/documents/recommendations_transform_dobrochesnist.pdf#page=60) називає робочу групу, тоді як [Додаток Г, с. 67](https://nuou.org.ua/assets/documents/recommendations_transform_dobrochesnist.pdf#page=67) відносить Анкету 2 до особового складу. Рішення має затвердити №5. Preview не зберігає й не подає відповіді; backend роль, DDL/API та scoring залишаються поза цим PR.
