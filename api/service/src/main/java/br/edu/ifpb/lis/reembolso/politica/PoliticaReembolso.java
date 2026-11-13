package br.edu.ifpb.lis.reembolso.politica;

import java.lang.reflect.Method;
import java.util.Arrays;
import java.util.Comparator;
import java.util.List;

/**
 * Política de reembolso e cancelamento (versão 2).
 * Cada método anotado com {@link RegraPolitica} é uma regra; a de menor
 * prioridade numérica que se aplica decide.
 */
public class PoliticaReembolso {

    public static final String VERSAO = "2";

    @RegraPolitica(id = "REG-SEG", prioridade = 10, requisitos = {"REQ-01"},
            decisao = Decisao.REVISAO_HUMANA,
            justificativa = "Sinal de fraude: encaminhar para revisão humana.")
    boolean fraude(Solicitacao s) {
        return Boolean.TRUE.equals(s.fraudeSuspeita());
    }

    @RegraPolitica(id = "REG-FALHA", prioridade = 20, requisitos = {"REQ-02"},
            decisao = Decisao.PERMITIR,
            justificativa = "Falha operacional identificada: reembolso elegível.")
    boolean falhaOperacional(Solicitacao s) {
        return "restaurante".equals(s.falhaOrigem()) || "transportadora".equals(s.falhaOrigem());
    }

    @RegraPolitica(id = "REG-PREMIUM-EXC", prioridade = 25, requisitos = {"REQ-05"},
            decisao = Decisao.PERMITIR,
            justificativa = "Exceção premium: pedido cancelado até 1 hora após despacho.")
    boolean excecaoPremium(Solicitacao s) {
        return Boolean.TRUE.equals(s.cancelamentoCliente())
                && Boolean.TRUE.equals(s.despachado())
                && Boolean.TRUE.equals(s.clientePremium())
                && s.horasAposDespacho() != null
                && s.horasAposDespacho() <= 1.0;
    }

    @RegraPolitica(id = "REG-CANCEL-ENVIADO", prioridade = 30, requisitos = {"REQ-03"},
            decisao = Decisao.NEGAR,
            justificativa = "Cancelamento após despacho sem exceção aplicável.")
    boolean cancelamentoAposDespacho(Solicitacao s) {
        return Boolean.TRUE.equals(s.cancelamentoCliente()) && Boolean.TRUE.equals(s.despachado());
    }

    @RegraPolitica(id = "REG-CANCEL-PRE", prioridade = 40, requisitos = {"REQ-04"},
            decisao = Decisao.PERMITIR,
            justificativa = "Cancelamento antes do despacho.")
    boolean cancelamentoAntesDoDespacho(Solicitacao s) {
        return Boolean.TRUE.equals(s.cancelamentoCliente()) && Boolean.FALSE.equals(s.despachado());
    }

    private final List<Method> regras = Arrays.stream(PoliticaReembolso.class.getDeclaredMethods())
            .filter(m -> m.isAnnotationPresent(RegraPolitica.class))
            .sorted(Comparator.comparingInt((Method m) -> m.getAnnotation(RegraPolitica.class).prioridade())
                    .thenComparing(m -> m.getAnnotation(RegraPolitica.class).id()))
            .toList();

    public Resultado decidir(Solicitacao s) {
        for (Method m : regras) {
            try {
                if ((boolean) m.invoke(this, s)) {
                    RegraPolitica r = m.getAnnotation(RegraPolitica.class);
                    return new Resultado(r.decisao(), r.id(), r.justificativa(), VERSAO);
                }
            } catch (ReflectiveOperationException e) {
                throw new IllegalStateException("Falha ao avaliar " + m.getName(), e);
            }
        }
        return new Resultado(Decisao.REVISAO_HUMANA, null,
                "Nenhuma regra conclusiva; aplicada a decisão padrão.", VERSAO);
    }
}
