"""Ponto de entrada do servidor MCP (FinanceiroMetodosMCP.exe).

Executável de console à parte: o programa de janela não tem entrada e saída
padrão, e é por elas que o Claude conversa com o servidor.
"""

from honorarios.mcp_servidor import main

if __name__ == "__main__":
    main()
