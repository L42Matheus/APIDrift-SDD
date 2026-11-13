package br.edu.ifpb.lis.reembolso.web;

import br.edu.ifpb.lis.reembolso.politica.PoliticaReembolso;
import br.edu.ifpb.lis.reembolso.politica.Resultado;
import br.edu.ifpb.lis.reembolso.politica.Solicitacao;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

/** Implementa a operação decidirReembolso do contrato contracts/vN/openapi.yaml. */
@RestController
@RequestMapping("/reembolsos")
public class DecisaoController {

    private final PoliticaReembolso politica = new PoliticaReembolso();

    @PostMapping("/decisoes")
    public Resultado decidir(@RequestBody Solicitacao solicitacao) {
        return politica.decidir(solicitacao);
    }
}
