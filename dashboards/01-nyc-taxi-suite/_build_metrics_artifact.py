import json

d = json.load(open("_product_metrics.json", encoding="utf-8"))

nsm = d["nsm_daily_trips_by_year"]
wp = d["guardrail_wait_and_pay_by_year"]
sm = d["guardrail_shared_match_by_year"]
fpm = d["proxy_fare_per_mile_by_year"]
liq = d["proxy_liquidity_by_year"]

YEARS = list(range(2019, 2027))


def sparkline(values, w=520, h=100, pad=10, color="#000"):
    lo, hi = min(values), max(values)
    span = (hi - lo) or 1
    n = len(values)
    pts = []
    for i, v in enumerate(values):
        x = pad + i * (w - 2 * pad) / (n - 1)
        y = h - pad - (v - lo) * (h - 2 * pad) / span
        pts.append((round(x, 1), round(y, 1)))
    path = "M" + " L".join(f"{x},{y}" for x, y in pts)
    dots = "".join(f'<circle cx="{x}" cy="{y}" r="3" class="spark-dot"/>' for x, y in pts)
    last_x, last_y = pts[-1]
    return f'''<svg viewBox="0 0 {w} {h}" class="sparkline" preserveAspectRatio="none" style="--spark:{color}">
      <path d="{path}" class="spark-line"/>{dots}
      <circle cx="{last_x}" cy="{last_y}" r="4.5" class="spark-end"/>
    </svg>'''


nsm_vals = [r["avg_daily"] for r in nsm]
wait_vals = [r["med_wait_sec"] for r in wp]
pay_vals = [r["med_hourly_pay"] for r in wp]
match_rate = [100 * r["n_matched"] / r["requested"] if r["requested"] else 0 for r in sm]
fpm_vals = [r["med_fare_per_mile"] for r in fpm]
liq_vals = [r["avg_trips_per_active_zone_hour"] for r in liq]

html = f'''<meta charset="utf-8">
<title>Продуктовые метрики: North Star, Guardrail, Proxy</title>
<style>
@font-face {{
  font-family: "Source Serif";
  src: local("Georgia");
}}
:root {{
  --bg: #f6f5f1;
  --surface: #ffffff;
  --surface-2: #edeae2;
  --border: #ddd7c9;
  --text: #1d1a14;
  --text-muted: #6c6555;
  --nsm: #a6740f;
  --nsm-soft: rgba(166,116,15,0.10);
  --guard: #a3453a;
  --guard-soft: rgba(163,69,58,0.08);
  --proxy: #2f7d6e;
  --proxy-soft: rgba(47,125,110,0.08);
  --font-display: Georgia, "Iowan Old Style", "Palatino Linotype", serif;
  --font-body: -apple-system, "Segoe UI", Roboto, Arial, sans-serif;
  --font-mono: ui-monospace, "SF Mono", "Cascadia Mono", Consolas, monospace;
}}
@media (prefers-color-scheme: dark) {{
  :root:not([data-theme="light"]) {{
    --bg: #16140f;
    --surface: #1e1b15;
    --surface-2: #262219;
    --border: #3a3527;
    --text: #efece3;
    --text-muted: #a39b87;
    --nsm: #dba43f;
    --nsm-soft: rgba(219,164,63,0.14);
    --guard: #e07869;
    --guard-soft: rgba(224,120,105,0.12);
    --proxy: #5bc3ae;
    --proxy-soft: rgba(91,195,174,0.12);
  }}
}}
:root[data-theme="dark"] {{
  --bg: #16140f;
  --surface: #1e1b15;
  --surface-2: #262219;
  --border: #3a3527;
  --text: #efece3;
  --text-muted: #a39b87;
  --nsm: #dba43f;
  --nsm-soft: rgba(219,164,63,0.14);
  --guard: #e07869;
  --guard-soft: rgba(224,120,105,0.12);
  --proxy: #5bc3ae;
  --proxy-soft: rgba(91,195,174,0.12);
}}
* {{ box-sizing: border-box; }}
body {{ margin: 0; background: var(--bg); color: var(--text); font-family: var(--font-body); font-size: 15.5px; line-height: 1.6; }}
.wrap {{ max-width: 900px; margin: 0 auto; padding: 48px 24px 80px; }}
.eyebrow {{ font-family: var(--font-mono); font-size: 11px; letter-spacing: 0.14em; text-transform: uppercase; color: var(--text-muted); }}
h1 {{ font-family: var(--font-display); font-weight: 600; font-size: clamp(28px,4vw,42px); margin: 6px 0 10px; text-wrap: balance; }}
.lede {{ color: var(--text-muted); max-width: 68ch; font-size: 16px; }}
.lede b {{ color: var(--text); }}

.tree {{ display: flex; flex-direction: column; align-items: center; gap: 0; margin: 44px 0 40px; }}
.tree-node {{ font-family: var(--font-mono); font-size: 12.5px; text-align: center; padding: 10px 16px; border-radius: 8px; border: 1px solid var(--border); background: var(--surface); }}
.tree-node.nsm {{ border-color: var(--nsm); background: var(--nsm-soft); font-weight: 700; font-size: 13.5px; }}
.tree-connector {{ width: 1px; height: 22px; background: var(--border); }}
.tree-row {{ display: flex; gap: 14px; flex-wrap: wrap; justify-content: center; }}
.tree-row .tree-node.guard {{ border-color: var(--guard); background: var(--guard-soft); }}
.tree-row .tree-node.proxy {{ border-color: var(--proxy); background: var(--proxy-soft); }}
.tree-labels {{ display: flex; gap: 14px; margin-top: 4px; font-size: 10.5px; color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.08em; }}

section.metric {{ background: var(--surface); border: 1px solid var(--border); border-radius: 14px; padding: 24px 26px; margin-bottom: 18px; }}
.metric-head {{ display: flex; align-items: baseline; justify-content: space-between; gap: 12px; flex-wrap: wrap; }}
.metric-tag {{ font-family: var(--font-mono); font-size: 10.5px; text-transform: uppercase; letter-spacing: 0.1em; padding: 3px 9px; border-radius: 999px; font-weight: 700; }}
.metric-tag.nsm {{ color: var(--nsm); background: var(--nsm-soft); }}
.metric-tag.guard {{ color: var(--guard); background: var(--guard-soft); }}
.metric-tag.proxy {{ color: var(--proxy); background: var(--proxy-soft); }}
h2 {{ font-family: var(--font-display); font-weight: 600; font-size: 21px; margin: 4px 0 2px; }}
.metric-def {{ color: var(--text-muted); font-size: 13.5px; margin: 2px 0 14px; max-width: 68ch; }}
.metric-body {{ display: grid; grid-template-columns: 190px 1fr; gap: 20px; align-items: start; }}
@media (max-width: 640px) {{ .metric-body {{ grid-template-columns: 1fr; }} }}
.metric-figures {{ display: flex; flex-direction: column; gap: 4px; }}
.figure-num {{ font-family: var(--font-mono); font-weight: 700; font-size: 26px; font-variant-numeric: tabular-nums; }}
.figure-delta {{ font-family: var(--font-mono); font-size: 12px; color: var(--text-muted); }}
.sparkline {{ width: 100%; height: 60px; margin-top: 8px; }}
.spark-line {{ fill: none; stroke: var(--spark); stroke-width: 2.2; }}
.spark-dot {{ fill: var(--surface); stroke: var(--spark); stroke-width: 1.4; }}
.spark-end {{ fill: var(--spark); }}
.insight {{ font-size: 14px; }}
.insight b {{ color: var(--text); }}

.synth {{ margin-top: 36px; padding-top: 24px; border-top: 1px solid var(--border); }}
.synth h2 {{ font-size: 19px; }}
.synth p {{ max-width: 72ch; color: var(--text-muted); font-size: 14.5px; }}
.synth p b {{ color: var(--text); }}
footer {{ margin-top: 32px; color: var(--text-muted); font-size: 12px; font-family: var(--font-mono); }}
</style>

<div class="wrap">
  <span class="eyebrow">TLC Trip Data 2019&ndash;2026 · Product metrics</span>
  <h1>North Star, Guardrail и Proxy метрики такси-маркетплейса NYC</h1>
  <p class="lede">6 метрик, выведенных из очищенного архива TLC (yellow/green/fhv/fhvhv, 2.1&nbsp;млрд поездок).
  <b>North Star</b> — единственная метрика ценности для гонки за ростом; <b>Guardrail</b> — что нельзя жертвовать ради роста NSM;
  <b>Proxy</b> — быстрые опережающие сигналы, которые двигаются раньше, чем NSM успевает отреагировать.</p>

  <div class="tree">
    <div class="tree-node nsm">Daily Completed Trips</div>
    <div class="tree-connector"></div>
    <div class="tree-row">
      <div class="tree-node guard">Rider Wait Time</div>
      <div class="tree-node guard">Driver Hourly Pay</div>
      <div class="tree-node guard">Shared-Ride Match Rate</div>
      <div class="tree-node proxy">Fare per Mile</div>
      <div class="tree-node proxy">Trips / Active Zone-Hour</div>
    </div>
    <div class="tree-labels"><span>3 guardrail</span><span>&nbsp;</span><span>2 proxy</span></div>
  </div>

  <section class="metric">
    <div class="metric-head"><h2>Daily Completed Trips</h2><span class="metric-tag nsm">North Star</span></div>
    <p class="metric-def">Среднесуточное число завершенных поездок (все 4 типа). Единственная метрика, напрямую отражающая объем доставленной ценности — совпадения спроса и предложения на рынке.</p>
    <div class="metric-body">
      <div class="metric-figures">
        <span class="figure-num">{nsm[-2]['avg_daily']:,.0f}</span>
        <span class="figure-delta">поездок/день, 2025</span>
        <span class="figure-delta">2019 пик: {nsm[0]['avg_daily']:,.0f}</span>
      </div>
      {sparkline(nsm_vals, color="var(--nsm)")}
    </div>
    <p class="insight">Провал COVID (2020: <b>&minus;51%</b> к 2019) и <b>7-летнее неполное восстановление</b> — к 2025 рынок вышел на 802K/день,
    это все еще <b>&minus;20% от пикового 2019</b>. Это должна быть метрика №1 в еженедельном обзоре: любая инициатива роста должна двигать именно ее,
    а не суррогаты вроде GMV, которые растут за счет цены (см. Fare per Mile ниже), а не реального объема спроса.</p>
  </section>

  <section class="metric">
    <div class="metric-head"><h2>Rider Wait Time</h2><span class="metric-tag guard">Guardrail</span></div>
    <p class="metric-def">Медианное время от запроса до подачи (request&#8594;pickup), только fhvhv (Uber/Lyft/Via/Juno) &mdash; единственный тип с явным полем времени запроса.</p>
    <div class="metric-body">
      <div class="metric-figures">
        <span class="figure-num">{wp[-2]['med_wait_sec']/60:.1f} мин</span>
        <span class="figure-delta">медиана, 2025</span>
        <span class="figure-delta">p90: {wp[-2]['p90_wait_sec']/60:.1f} мин</span>
      </div>
      {sparkline(wait_vals, color="var(--guard)")}
    </div>
    <p class="insight">Держится в узком коридоре 4&ndash;5 минут, но заметно хуже всего в <b>2021&ndash;2022</b> (4.9 мин медиана) &mdash; ровно когда предложение
    водителей просело сильнее всего после пандемии. Важно: рост NSM в 2022&ndash;2025 <b>не</b> сопровождался ухудшением ожидания &mdash; значит,
    восстановление роста шло за счет возврата водителей на платформу, а не за счет перегрузки существующего супплая. Если этот guardrail
    начнет расти вместе с NSM &mdash; это будет ранний сигнал, что рост уже упирается в потолок предложения.</p>
  </section>

  <section class="metric">
    <div class="metric-head"><h2>Driver Hourly Pay</h2><span class="metric-tag guard">Guardrail</span></div>
    <p class="metric-def">Медианная эффективная почасовая оплата водителя (driver_pay / длительность поездки), fhvhv.</p>
    <div class="metric-body">
      <div class="metric-figures">
        <span class="figure-num">${wp[-2]['med_hourly_pay']:.2f}/ч</span>
        <span class="figure-delta">медиана, 2025</span>
        <span class="figure-delta">2019: ${wp[0]['med_hourly_pay']:.2f}/ч</span>
      </div>
      {sparkline(pay_vals, color="var(--guard)")}
    </div>
    <p class="insight">Стабильный рост <b>+29%</b> за 7 лет (${wp[0]['med_hourly_pay']:.0f}&rarr;${wp[-2]['med_hourly_pay']:.0f}), с заметным ускорением
    начиная с 2023 года &mdash; это прямое отражение введенного TLC минимального стандарта оплаты водителей (driver pay floor). Продуктовый вывод:
    для этого рынка guardrail по оплате водителя <b>защищен регуляторно</b>, а не только решением платформы &mdash; значит unit-экономика роста NSM
    должна закладывать этот пол как жесткое ограничение, а не как переменную для оптимизации маржи.</p>
  </section>

  <section class="metric">
    <div class="metric-head"><h2>Shared-Ride Match Rate</h2><span class="metric-tag guard">Guardrail</span></div>
    <p class="metric-def">Доля запросов на совместную поездку (shared_request_flag=Y), реально сматченных с попутчиком (shared_match_flag=Y), fhvhv.</p>
    <div class="metric-body">
      <div class="metric-figures">
        <span class="figure-num">{match_rate[-2]:.0f}%</span>
        <span class="figure-delta">match rate, 2025</span>
        <span class="figure-delta">запросов: {sm[-2]['requested']:,.0f}</span>
      </div>
      {sparkline(match_rate, color="var(--guard)")}
    </div>
    <p class="insight">Самая резкая история в наборе: запросов на shared ride в 2021 было <b>в 178 раз меньше</b>, чем в 2019 (284K vs 50.8M) &mdash;
    это не падение спроса, а <b>приостановка продукта</b> (UberPool/Lyft&nbsp;Line на паузе в COVID). Но даже когда запросы начали возвращаться
    (2022: 1.8M), match rate провалился до <b>24%</b> &mdash; продукту не хватало плотности спроса, чтобы находить попутчиков, и это отдельная,
    более медленная история восстановления, чем у самого спроса на sharing. К 2025&ndash;2026 match rate вернулся к ~58%, синхронно с
    восстановлением ликвидности (см. Proxy ниже) &mdash; sharing работает только когда рынок достаточно плотный.</p>
  </section>

  <section class="metric">
    <div class="metric-head"><h2>Fare per Mile</h2><span class="metric-tag proxy">Proxy</span></div>
    <p class="metric-def">Медианный тариф за милю (base_passenger_fare / trip_miles), fhvhv &mdash; быстрый сигнал дисбаланса спроса и предложения.</p>
    <div class="metric-body">
      <div class="metric-figures">
        <span class="figure-num">${fpm[-2]['med_fare_per_mile']:.2f}</span>
        <span class="figure-delta">за милю, 2025</span>
        <span class="figure-delta">2019: ${fpm[0]['med_fare_per_mile']:.2f}</span>
      </div>
      {sparkline(fpm_vals, color="var(--proxy)")}
    </div>
    <p class="insight">Растет почти монотонно, <b>+63.5%</b> за 7 лет &mdash; быстрее, чем оплата водителя (+29%), значит маржа платформы на милю,
    вероятно, расширилась (либо часть роста &mdash; pass-through congestion pricing 2025 и инфляция). Это метрика для <b>ежедневного</b>, а не
    еженедельного мониторинга: она реагирует на дисбаланс спроса/предложения в реальном времени, задолго до того как это отразится на NSM
    или на wait time &mdash; ранний тревожный сигнал перед тем, как рост начнет вымывать чувствительных к цене райдеров.</p>
  </section>

  <section class="metric">
    <div class="metric-head"><h2>Trips per Active Zone-Hour</h2><span class="metric-tag proxy">Proxy</span></div>
    <p class="metric-def">Среднее число поездок на активную зону-час (плотность/ликвидность рынка), fhvhv.</p>
    <div class="metric-body">
      <div class="metric-figures">
        <span class="figure-num">{liq[-2]['avg_trips_per_active_zone_hour']:.0f}</span>
        <span class="figure-delta">поездок/зона-час, 2025</span>
        <span class="figure-delta">2019: {liq[0]['avg_trips_per_active_zone_hour']:.0f}</span>
      </div>
      {sparkline(liq_vals, color="var(--proxy)")}
    </div>
    <p class="insight">Самое интересное расхождение во всем наборе: ликвидность рынка <b>уже полностью восстановилась</b> до уровня 2019 (даже
    чуть выше), при этом число активных зон не изменилось (~252 стабильно) &mdash; но NSM все еще на 20% ниже пика 2019. Значит проблема роста
    не в эффективности мэтчинга рынка (она в порядке) и не в сжатии географии (зоны те же) &mdash; она в том, что город в целом генерирует
    меньше поездок, чем до пандемии (структурный эффект удаленной работы). Не путать эту метрику с NSM: здоровый proxy при недовосстановленном
    NSM указывает точно, где искать причину &mdash; в спросе на уровне города, а не в механике платформы.</p>
  </section>

  <div class="synth">
    <h2>Синтез</h2>
    <p>Вся история архива укладывается в одну арку: <b>обвал 2020 &rarr; supply-shock 2021&ndash;2022 &rarr; неполное восстановление к 2025&ndash;2026</b>.
    Guardrail-ы показывают, что восстановление роста было <b>здоровым</b> &mdash; не за счет водителей (оплата растет) и не за счет качества сервиса
    (wait time стабилен). Proxy-метрики расходятся по смыслу: fare/mile говорит о растущей ценовой власти платформы, а liquidity &mdash; о том, что
    оставшийся разрыв с 2019 не в механике рынка, а в структурном спросе города. Итого: если ставить цель вернуть NSM к пиковым 998K/день, рычаг &mdash;
    не в оптимизации мэтчинга (он уже на пределе эффективности 2019 года), а в привлечении нового спроса &mdash; тех поездок, что город
    делал в 2019 и больше не делает.</p>
  </div>

  <footer>Источник: TLC_Trip_Data_clean (2019&ndash;2026, 2 100 954 665 поездок) · approx_quantile (t-digest) по fhvhv, 1.6 млрд строк</footer>
</div>
'''

out_path = r"C:\Users\andrn\AppData\Local\Temp\claude\C--Users-andrn-HSE-NYC\e9bb64d4-676f-4446-97a9-a4164a16a604\scratchpad\nyc_taxi_product_metrics.html"
with open(out_path, "w", encoding="utf-8") as f:
    f.write(html)
print("wrote", out_path, len(html), "chars")
