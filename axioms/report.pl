% Shared report predicates of the 3SE axioms.
%
% The axioms in domain/ are integrity checks over the rules of core/ and the
% facts of facts.pl. Each one adds clauses to:
%
%   violation(Term)  the ontology contradicts an axiom (must be empty)
%   warning(Term)    expected but not required (same severity as the
%                    warnings printed by the injection scripts)
%
% Every axiom states where it comes from. Run check/0 to list both.
%
% Load this file before the files of domain/: it declares the two predicates
% multifile so that each domain file can contribute its own clauses.

:- multifile violation/1, warning/1.

%! check is semidet.
%  Print every violation and warning; succeed only when there is no violation.
check :-
    findall(V, violation(V), Vs),
    findall(W, warning(W), Ws),
    forall(member(V, Vs), format("VIOLATION: ~q~n", [V])),
    forall(member(W, Ws), format("warning:   ~q~n", [W])),
    length(Vs, NV),
    length(Ws, NW),
    format("~d violation(s), ~d warning(s)~n", [NV, NW]),
    NV =:= 0.
