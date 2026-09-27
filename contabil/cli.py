# -*- coding: utf-8 -*-
"""Uso: python -m contabil.cli <pasta_de_entrada> <saida.xlsx>"""
import sys, os, glob
from .pipeline import process
from .build import build_workbook


def main():
    if len(sys.argv) < 3:
        print("Uso: python -m contabil.cli <pasta_de_entrada> <saida.xlsx>")
        sys.exit(1)
    pasta, saida = sys.argv[1], sys.argv[2]
    paths = [p for ext in ("*.pdf", "*.xlsx", "*.xlsm")
             for p in glob.glob(os.path.join(pasta, ext))]
    if not paths:
        print("Nenhum PDF/XLSX encontrado em", pasta)
        sys.exit(1)
    tx, rep = process(paths)
    build_workbook(tx, saida)
    print(f"{rep['total']} lançamentos -> {saida}")
    for x in rep["por_fonte"]:
        print(f"  {x['fonte']:30} n={x['n']:4d}  ent={x['entradas']:12,.2f}  sai={x['saidas']:12,.2f}")
    if rep["ignorados"]:
        print("Ignorados:", ", ".join(rep["ignorados"]))


if __name__ == "__main__":
    main()
