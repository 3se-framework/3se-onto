% Roles and analyses (rules in core/roles.pl).

:- multifile violation/1, warning/1.

:- dynamic related/2.

% A role cannot be a content term of a breakdown structure, conceptual model
% or analysis (scripts/inject_responsible_roles.py fails on it).

violation(role_in_related(Bca, Role)) :-
    bca(Bca),
    related(Bca, Role),
    role(Role).

% Every analysis has at least one breakdown structure and one conceptual
% model in its related terms, and an accountable role
% (scripts/inject_analysis_roles.py warns on the first two).

warning(analysis_without_breakdown_structure(A)) :-
    analysis(A),
    \+ ( related(A, B), breakdown_structure(B) ).

warning(analysis_without_conceptual_model(A)) :-
    analysis(A),
    \+ ( related(A, M), conceptual_model(M) ).

warning(analysis_without_accountable_role(A)) :-
    analysis(A),
    \+ accountable_role(A, _).

% Responsibilities follow accountabilities (core/roles.pl: responsibility_gap/3).

warning(responsibility_gap(Kind, Role, Content)) :-
    responsibility_gap(Kind, Role, Content).
