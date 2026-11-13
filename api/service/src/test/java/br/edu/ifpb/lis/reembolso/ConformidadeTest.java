package br.edu.ifpb.lis.reembolso;

import static org.assertj.core.api.Assertions.assertThat;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import br.edu.ifpb.lis.reembolso.politica.PoliticaReembolso;
import br.edu.ifpb.lis.reembolso.politica.Solicitacao;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.io.InputStream;
import java.util.stream.Stream;
import java.util.stream.StreamSupport;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.MethodSource;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;

/** Testes de conformidade: os casos rotulados da política vigente contra o código. */
@SpringBootTest
@AutoConfigureMockMvc
class ConformidadeTest {

    private static final ObjectMapper JSON = new ObjectMapper();

    static Stream<JsonNode> casos() throws Exception {
        try (InputStream in = ConformidadeTest.class.getResourceAsStream("/casos-conformidade.json")) {
            JsonNode root = JSON.readTree(in);
            return StreamSupport.stream(root.get("casos").spliterator(), false).toList().stream();
        }
    }

    @ParameterizedTest(name = "{index}: {0}")
    @MethodSource("casos")
    void politicaDecideComoEsperado(JsonNode caso) throws Exception {
        Solicitacao s = JSON.treeToValue(caso.get("solicitacao"), Solicitacao.class);
        assertThat(new PoliticaReembolso().decidir(s).decisao().name())
                .as(caso.get("id").asText())
                .isEqualTo(caso.get("esperado").asText());
    }

    @Autowired
    MockMvc mvc;

    @Test
    void endpointSegueOContrato() throws Exception {
        mvc.perform(post("/reembolsos/decisoes").contentType(MediaType.APPLICATION_JSON).content("""
                {"fraudeSuspeita": false, "falhaOrigem": "nenhuma", "cancelamentoCliente": true,
                 "despachado": true, "clientePremium": true, "horasAposDespacho": 0.5}"""))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.decisao").value("PERMITIR"))
                .andExpect(jsonPath("$.regraId").value("REG-PREMIUM-EXC"))
                .andExpect(jsonPath("$.versaoPolitica").value("2"));
    }
}
