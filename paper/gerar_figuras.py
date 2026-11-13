"""Gera as figuras do projeto (trilha de APIs) a partir de results/.

Entrada: ``api_mutation_summary.csv`` e ``api_mutation_observations.csv`` (L0-L3,
determinístico) e, se existirem, ``api_mutation_llm_*`` em results/ (Claude) e
results/gpt/ (GPT), de onde vem o nível L4. Para reproduzir sem chave de API:
``apidrift mutate --semantic --offline --cache llm_cache/claude.json``.

Uso: python gerar_figuras_api.py <results> <figs>
"""
import csv, os, sys
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Patch
from matplotlib.ticker import FuncFormatter

RES, OUT = sys.argv[1], sys.argv[2]
os.makedirs(OUT, exist_ok=True)

BLUE, ORANGE, AQUA = "#2a78d6", "#eb6834", "#1baf7a"
INK, INK2, GRID, LIGHT = "#0b0b0b", "#52514e", "#e4e3df", "#f0efec"
plt.rcParams.update({
    "font.family": "DejaVu Sans", "font.size": 9, "axes.edgecolor": INK2,
    "axes.labelcolor": INK, "xtick.color": INK2, "ytick.color": INK2,
    "axes.spines.top": False, "axes.spines.right": False,
    "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.6,
    "axes.axisbelow": True, "savefig.bbox": "tight", "savefig.dpi": 300,
})
BR = FuncFormatter(lambda v, _: (f"{v:.1f}" if v % 1 else f"{v:.0f}").replace(".", ","))
br = lambda v: f"{v:.2f}".replace(".", ",")
LV = {"L0_sem_verificacao": "L0\nsem verificação", "L1_versao": "L1\nversão",
      "L2_testes_contrato": "L2\ntestes e\nesquema", "L3_sdd": "L3\nrastreab.\nSDD"}
SHORT = {"L0_sem_verificacao": "L0", "L1_versao": "L1", "L2_testes_contrato": "L2", "L3_sdd": "L3"}


def rows(name, base=None):
    with open(os.path.join(base or RES, name), newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


ms = rows("api_mutation_summary.csv")
mo = rows("api_mutation_observations.csv")
for sub, label in (("", "Claude"), ("gpt", "GPT")):
    d = os.path.join(RES, sub)
    if not os.path.exists(os.path.join(d, "api_mutation_llm_summary.csv")):
        continue
    key = f"L4_{label}"
    LV[key], SHORT[key] = f"L4\nIA ({label})", f"L4-{label[0]}"
    ms += [dict(r, level=key) for r in rows("api_mutation_llm_summary.csv", d) if r["level"] == "L4_semantica"]
    mo += [dict(r, level=key) for r in rows("api_mutation_llm_observations.csv", d) if r["level"] == "L4_semantica"]

N_DRIFT = sum(1 for r in mo if r["level"] == "L0_sem_verificacao" and r["drift"] == "True")
N_BENIGN = sum(1 for r in mo if r["level"] == "L0_sem_verificacao" and r["drift"] == "False")


def save(fig, name):
    for ext in ("pdf", "png"):
        fig.savefig(os.path.join(OUT, f"{name}.{ext}"))
    plt.close(fig)


# ---------- Figura: sensibilidade e alarme falso por nível ----------
labels = [LV[r["level"]] for r in ms]
sens = [float(r["sensitivity"]) for r in ms]
far = [float(r["false_alarm_rate"]) for r in ms]
tp = [int(r["tp"]) for r in ms]
fp = [int(r["fp"]) for r in ms]
fig, ax = plt.subplots(figsize=(6.6, 3.0))
x = range(len(labels)); w = 0.36
b1 = ax.bar([i - w / 2 - 0.01 for i in x], sens, w, color=BLUE,
            label=f"Sensibilidade (derivas detectadas / {N_DRIFT})")
b2 = ax.bar([i + w / 2 + 0.01 for i in x], far, w, color=ORANGE,
            label=f"Alarme falso (mudanças benignas barradas / {N_BENIGN})")
for bars, ks, n in ((b1, tp, N_DRIFT), (b2, fp, N_BENIGN)):
    for b, k in zip(bars, ks):
        ax.annotate(f"{br(b.get_height())}\n({k}/{n})", (b.get_x() + b.get_width() / 2, b.get_height()),
                    xytext=(0, 2), textcoords="offset points", ha="center", va="bottom", fontsize=7, color=INK)
ax.set_xticks(list(x)); ax.set_xticklabels(labels, fontsize=7.5)
ax.set_ylim(0, 1.18); ax.set_ylabel("Proporção"); ax.yaxis.set_major_formatter(BR)
ax.grid(axis="x", visible=False)
ax.legend(frameon=False, loc="upper left", fontsize=7.5)
save(fig, "fig_api_sensibilidade")

# ---------- Figura: matriz de detecção ----------
muts = sorted({r["mutation"] for r in mo}, key=lambda m: (m[0] != "M", m))
levels = [r["level"] for r in ms]
det = {(r["mutation"], r["level"]): r for r in mo}
fig, ax = plt.subplots(figsize=(6.6, 0.42 * len(levels) + 0.9))
ax.grid(False)
for j, m in enumerate(muts):
    for i, lv in enumerate(levels):
        r = det[(m, lv)]
        detected, drift = r["detected"] == "True", r["drift"] == "True"
        color = (BLUE if detected else LIGHT) if drift else (ORANGE if detected else LIGHT)
        ax.add_patch(plt.Rectangle((j + 0.04, i + 0.06), 0.92, 0.88, color=color, linewidth=0))
        if detected and lv.startswith("L4") and r["categories"] == "semantica":
            ax.text(j + 0.5, i + 0.52, "IA", ha="center", va="center", fontsize=6, color="white",
                    fontweight="bold")
ax.set_xlim(0, len(muts)); ax.set_ylim(0, len(levels))
ax.set_xticks([j + 0.5 for j in range(len(muts))]); ax.set_xticklabels(muts, rotation=90, fontsize=7.5)
ax.set_yticks([i + 0.5 for i in range(len(levels))])
ax.set_yticklabels([LV[l].replace("\n", " ") for l in levels], fontsize=7.5)
ax.invert_yaxis()
for s in ax.spines.values():
    s.set_visible(False)
ax.tick_params(length=0)
ax.axvline(N_DRIFT, color=INK2, linewidth=1.0)
ax.text(N_DRIFT / 2, -0.25, f"{N_DRIFT} mutações com deriva", ha="center", fontsize=7.5, color=INK2)
ax.text(N_DRIFT + N_BENIGN / 2, -0.25, f"{N_BENIGN} mudanças benignas", ha="center", fontsize=7.5, color=INK2)
ax.legend(handles=[Patch(color=BLUE, label="Deriva detectada"),
                   Patch(color=ORANGE, label="Benigna barrada (alarme falso)"),
                   Patch(color=LIGHT, label="Não sinalizado")],
          frameon=False, loc="upper center", bbox_to_anchor=(0.5, -0.16), ncol=3, fontsize=7)
save(fig, "fig_api_matriz")

# ---------- Figura: decisões erradas liberadas ----------
vals = [int(r["decisoes_erradas_liberadas"]) for r in ms]
fig, ax = plt.subplots(figsize=(4.2, 2.4))
bars = ax.bar([SHORT[r["level"]] for r in ms], vals, 0.6, color=BLUE)
for b in bars:
    ax.annotate(f"{int(b.get_height())}", (b.get_x() + b.get_width() / 2, b.get_height()), xytext=(0, 2),
                textcoords="offset points", ha="center", va="bottom", fontsize=7.5, color=INK)
ax.set_ylabel("Decisões erradas liberadas", fontsize=9)
ax.set_ylim(0, max(vals) * 1.25 if max(vals) else 1)
ax.grid(axis="x", visible=False)
save(fig, "fig_api_impacto")
print("Figuras geradas em", OUT, "níveis:", [SHORT[r["level"]] for r in ms])
