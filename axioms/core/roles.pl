% Analyses, breakdown structures, conceptual models and roles, and the
% derivation of role responsibilities that scripts/inject_analysis_roles.py and
% scripts/inject_responsible_roles.py apply to the JSON files.

:- dynamic
    related/2, is_accountable_for/2, is_responsible_for/2, is_supporting/2.

%! role(?R) is nondet.
role(R) :- is_a(R, 'role-3se'), R \== 'role-3se'.

%! analysis(?A) is nondet.
analysis(A) :- is_a(A, 'analysis-3se'), A \== 'analysis-3se'.

%! breakdown_structure(?B) is nondet.
breakdown_structure(B) :- is_a(B, 'breakdown-structure-3se'), B \== 'breakdown-structure-3se'.

%! conceptual_model(?M) is nondet.
conceptual_model(M) :- is_a(M, 'conceptual-model-3se'), M \== 'conceptual-model-3se'.

%! bca(?X) is nondet.
%  X is a breakdown structure, a conceptual model or an analysis.
bca(X) :- breakdown_structure(X).
bca(X) :- conceptual_model(X).
bca(X) :- analysis(X).

%! accountable_role(?Analysis, ?Role) is nondet.
%  Role is accountable for the analysis, directly or through a more general
%  analysis it specialises (e.g. the system risk engineer for the safety risk
%  analysis, through the risk analysis).
accountable_role(A, R) :-
    is_accountable_for(R, A0),
    is_a(A, A0).

%! derived_responsible(?Role, ?Content) is nondet.
%  Content is a term related to a breakdown structure, conceptual model or
%  analysis the role is accountable for, other than such a BCA or a role
%  (mirrors scripts/inject_responsible_roles.py).
derived_responsible(Role, Content) :-
    role(Role),
    is_accountable_for(Role, Bca),
    bca(Bca),
    related(Bca, Content),
    \+ bca(Content),
    \+ role(Content).

%! responsibility_gap(?Kind, ?Role, ?Content) is nondet.
%  Kind is missing (derived but not declared in isResponsibleFor) or stale
%  (declared but not derived). Only roles accountable for at least one BCA
%  are checked, like the injection script.
responsibility_gap(missing, Role, Content) :-
    derived_responsible(Role, Content),
    \+ is_responsible_for(Role, Content).
responsibility_gap(stale, Role, Content) :-
    role(Role),
    once((is_accountable_for(Role, Bca), bca(Bca))),
    is_responsible_for(Role, Content),
    \+ derived_responsible(Role, Content).
