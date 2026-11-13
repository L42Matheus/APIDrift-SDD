package br.edu.ifpb.lis.reembolso.politica;

import java.lang.annotation.ElementType;
import java.lang.annotation.Retention;
import java.lang.annotation.RetentionPolicy;
import java.lang.annotation.Target;

/**
 * Marca um método como regra de negócio rastreável.
 * O verificador do APIDrift-SDD lê estes atributos e o corpo do método.
 */
@Retention(RetentionPolicy.RUNTIME)
@Target(ElementType.METHOD)
public @interface RegraPolitica {
    String id();
    int prioridade();
    String[] requisitos();
    Decisao decisao();
    String justificativa();
}
