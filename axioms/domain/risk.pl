% Risk and opportunity scales (descriptions of Risk and Opportunity).

:- multifile violation/1, warning/1.

:- dynamic matrix/4.

% Ordered from the lowest to the highest value.

scale(likelihood,        [rare, unlikely, possible, likely, almost_certain]).
scale(severity,          [insignificant, minor, moderate, major, blocker]).
scale(benefit,           [insignificant, minor, moderate, major, promoter]).
scale(risk_level,        [acceptable, tolerable, undesirable, unacceptable]).
scale(opportunity_level, [negligible, interesting, attractive, exceptional]).

% A risk (opportunity) combines a likelihood with a severity (benefit) into a
% level. The ontology fixes the scales but not the matrix, so none is given
% here: assert matrix(Kind, Likelihood, Consequence, Level) facts, with Kind
% risk or opportunity, and the three axioms below check it.
%   - complete: once any cell is given, every likelihood x consequence cell
%     is;
%   - in scale: all values belong to the scales above;
%   - monotonic (assumption, not stated in the ontology): a higher likelihood
%     or consequence never yields a lower level.

matrix_dimensions(risk,        severity, risk_level).
matrix_dimensions(opportunity, benefit,  opportunity_level).

rank(Scale, Value, Rank) :-
    scale(Scale, Values),
    nth1(Rank, Values, Value).

violation(matrix_incomplete(Kind, L, C)) :-
    matrix_dimensions(Kind, ConsequenceScale, _),
    once(matrix(Kind, _, _, _)),
    scale(likelihood, Ls),
    scale(ConsequenceScale, Cs),
    member(L, Ls),
    member(C, Cs),
    \+ matrix(Kind, L, C, _).

violation(matrix_value_out_of_scale(Kind, L, C, V)) :-
    matrix_dimensions(Kind, ConsequenceScale, LevelScale),
    matrix(Kind, L, C, V),
    (   \+ rank(likelihood, L, _)
    ;   \+ rank(ConsequenceScale, C, _)
    ;   \+ rank(LevelScale, V, _)
    ).

violation(matrix_non_monotonic(Kind, L1-C1-V1, L2-C2-V2)) :-
    matrix_dimensions(Kind, ConsequenceScale, LevelScale),
    matrix(Kind, L1, C1, V1),
    matrix(Kind, L2, C2, V2),
    rank(likelihood, L1, RL1), rank(likelihood, L2, RL2), RL1 =< RL2,
    rank(ConsequenceScale, C1, RC1), rank(ConsequenceScale, C2, RC2), RC1 =< RC2,
    rank(LevelScale, V1, RV1), rank(LevelScale, V2, RV2), RV1 > RV2.
