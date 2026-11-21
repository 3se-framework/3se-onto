% Mappings to referenced standards (README, "How 3SE terms relate…").
% A 3SE term is mapped to terms of the referenced standards, never to
% another 3SE term.

:- multifile violation/1, warning/1.

:- dynamic
    close_match/2, exact_match/2, broad_match/2, narrow_match/2, related_match/2.

match_relation(close_match).
match_relation(exact_match).
match_relation(broad_match).
match_relation(narrow_match).
match_relation(related_match).

is_3se_term(T) :- sub_atom(T, _, 4, 0, '-3se').

violation(match_to_3se_term(S, Rel, T)) :-
    match_relation(Rel),
    Fact =.. [Rel, S, T],
    call(Fact),
    is_3se_term(T).
