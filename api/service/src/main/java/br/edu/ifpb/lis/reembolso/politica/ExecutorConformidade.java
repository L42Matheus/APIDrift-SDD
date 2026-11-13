package br.edu.ifpb.lis.reembolso.politica;

import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.nio.charset.StandardCharsets;

/**
 * Executa casos sem Spring, para os testes de conformidade do verificador.
 * Entrada (stdin, TSV): id, fraude, falha, cancelamento, despachado, premium, horas.
 * Valores vazios significam desconhecido. Saída (stdout, TSV): id, decisão, regra.
 */
public final class ExecutorConformidade {
    private ExecutorConformidade() {
    }

    private static Boolean bool(String v) {
        return v.isEmpty() ? null : Boolean.valueOf(v);
    }

    public static void main(String[] args) throws Exception {
        PoliticaReembolso politica = new PoliticaReembolso();
        BufferedReader in = new BufferedReader(new InputStreamReader(System.in, StandardCharsets.UTF_8));
        String line;
        while ((line = in.readLine()) != null) {
            if (line.isBlank()) {
                continue;
            }
            String[] f = line.split("\t", -1);
            Solicitacao s = new Solicitacao(bool(f[1]), f[2].isEmpty() ? null : f[2], bool(f[3]), bool(f[4]),
                    bool(f[5]), f[6].isEmpty() ? null : Double.valueOf(f[6]));
            Resultado r = politica.decidir(s);
            System.out.println(f[0] + "\t" + r.decisao() + "\t" + (r.regraId() == null ? "" : r.regraId()));
        }
    }
}
