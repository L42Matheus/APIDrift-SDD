package br.edu.ifpb.lis.reembolso.politica;

/** Fatos estruturados de uma solicitação. Campos nulos significam "desconhecido". */
public record Solicitacao(
        Boolean fraudeSuspeita,
        String falhaOrigem,
        Boolean cancelamentoCliente,
        Boolean despachado,
        Boolean clientePremium,
        Double horasAposDespacho) {
}
