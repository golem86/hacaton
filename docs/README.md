# Документація Integrity Management Dashboard

Документи поділено на дві групи. **Для журі** — чинний опис продукту станом на зафіксований код `6629c74`. **Робочі матеріали** — контракти, звіти й рішення, які команда писала під час роботи. Вони показують, як ухвалювались рішення, але описують стан на дату документа. Кожен такий файл має банер «Історичний робочий документ».

## Для журі

Обов'язкові матеріали завдання 3:

| № | Що вимагає завдання | Документ |
|---|---|---|
| 1 | Робочий MVP | [README](../README.md): «Як запустити» і «Демонстрація» |
| 2 | Демонстрація проходження оцінювання | [demo-scenario.md](demo-scenario.md), відео в README |
| 3 | Приклад розрахунку Integrity Index | [methodology.md](methodology.md), розділ 10 |
| 4 | Приклад Dashboard керівника | [dashboard-example.md](dashboard-example.md) |
| 5 | Приклади рекомендацій | [methodology.md](methodology.md), розділи 7 і 10 |
| 6 | Захист анонімності | [anonymity.md](anonymity.md) |
| 7 | Самооцінка vs об'єктивні показники | [objective-comparison-example.md](objective-comparison-example.md) |
| 8 | Економія часу | [time-savings.md](time-savings.md) |
| 9 | Карта інтеграції | [integration-map.md](integration-map.md) |
| 10 | Аналіз зловживань і запобіжників | [abuse-analysis.md](abuse-analysis.md) |
| 11 | Як ми використали ШІ | [ai.md](ai.md) |
| 12 | Концепція інтеграції з іншими рішеннями | [integration-concept.md](integration-concept.md) |

Опис продукту й методики:
- [architecture.md](architecture.md) — архітектура, компоненти й потоки даних.
- [security.md](security.md) — правила роботи з даними.
- [maturity-levels.md](maturity-levels.md) — зони й рівні зрілості для кольорового кодування.
- [maturity-annex-v.md](maturity-annex-v.md) і [annex-mapping.md](annex-mapping.md) — зрілість за Додатком В і відповідність критеріїв.
- [API_CONTRACT.md](API_CONTRACT.md) — контракт API.

Запуск, розгортання й експлуатація:
- [DOCKER_DEMO.md](DOCKER_DEMO.md) — локальний Docker-стек: деталі й усунення проблем.
- [LOCAL_DEV.md](LOCAL_DEV.md) — запуск без Docker, перевірки й кількість тестів.
- [DEMO_DATA.md](DEMO_DATA.md) — синтетичні демо-цикли й підготовка до запису відео.
- [ANALYTICS_DEMO.md](ANALYTICS_DEMO.md) — показ аналітики через API.
- [LOCAL_LM.md](LOCAL_LM.md) — локальна мовна модель: встановлення й перевірки.
- [DATABASE_UPGRADE.md](DATABASE_UPGRADE.md) — версії схеми й міграції.
- [BACKUP_RESTORE.md](BACKUP_RESTORE.md) — резервні копії й відновлення робочого сервера.
- [TAILSCALE_ACCESS.md](TAILSCALE_ACCESS.md) — доступ журі до робочого сервера.
- [branding/README.md](branding/README.md) — логотип команди.

## Робочі матеріали команди

На ці файли посилаються код, тести або інші документи, тому вони лишаються на своїх місцях.

- **Контракти V2:**
  - [V2_INTEGRATION_CONTRACT.md](V2_INTEGRATION_CONTRACT.md) — погодження концепції V2;
  - [V2_HARDENING_CONTRACT.md](V2_HARDENING_CONTRACT.md) — ролі й захист після аудиту; чинні правила;
  - [V2_BACKEND_IMPLEMENTATION.md](V2_BACKEND_IMPLEMENTATION.md);
  - [USER_UNIT_RESULTS_API_PROPOSAL.md](USER_UNIT_RESULTS_API_PROPOSAL.md) — «Результати підрозділу», реалізовано.
- **Анкети Додатка В і експертна роль:**
  - `QUESTIONNAIRE_*`, `OFFICIAL_*`, `EXPERT_ROLE_*`, [API_CONTRACT_SCHEMA3_ADDENDUM.md](API_CONTRACT_SCHEMA3_ADDENDUM.md);
  - звіти в [reports/](reports/).
- **Аналітика й Dashboard:** [ASSESSMENT_MANAGER_V2.md](ASSESSMENT_MANAGER_V2.md), [analytics-integration.md](analytics-integration.md), [ANALYTICS_DASHBOARD_HANDOFF.md](ANALYTICS_DASHBOARD_HANDOFF.md), [DASHBOARD_PLAN.md](DASHBOARD_PLAN.md), [CONTRIBUTIONS_ANALYTICS.md](CONTRIBUTIONS_ANALYTICS.md).
- **Перевірки:** [FINAL_BACKEND_QA.md](FINAL_BACKEND_QA.md), [SUPPRESSION_ATTACK_TEST_REPORT.md](SUPPRESSION_ATTACK_TEST_REPORT.md).

Числа тестів у робочих документах описують стан на їхню дату. Чинні кількості — у [LOCAL_DEV.md](LOCAL_DEV.md).
