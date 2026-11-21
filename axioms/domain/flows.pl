% Flows and exchanges.
% What activities and functions produce or consume, and what interfaces
% convey, is a flow or an exchange.

:- multifile violation/1, warning/1.

:- dynamic produces/2, consumes/2, conveys/2.

flow_relation(produces).
flow_relation(consumes).
flow_relation(conveys).

flow_or_exchange(T) :- is_a(T, 'flow-3se').
flow_or_exchange(T) :- is_a(T, 'exchange-3se').

violation(not_a_flow_or_exchange(S, Rel, T)) :-
    flow_relation(Rel),
    Fact =.. [Rel, S, T],
    call(Fact),
    \+ flow_or_exchange(T).
