% Entry point: consult this file from SWI-Prolog, then run check/0.
%
%   swipl axioms/load.pl
%   ?- check.
%
% facts.pl     generated from terms/ by scripts/generate_prolog.py
% report.pl    violation/1, warning/1 and check/0 (load before domain/)
% core/        domain-neutral rules: closures, relation inheritance, roles
% domain/      3SE axioms, one file per set of rules

:- ensure_loaded(facts).
:- ensure_loaded(report).

:- ensure_loaded('core/closures').
:- ensure_loaded('core/inheritance').
:- ensure_loaded('core/roles').

:- ensure_loaded('domain/status').
:- ensure_loaded('domain/mappings').
:- ensure_loaded('domain/flows').
:- ensure_loaded('domain/variants').
:- ensure_loaded('domain/analyses').
:- ensure_loaded('domain/inheritance').
:- ensure_loaded('domain/shapes').
:- ensure_loaded('domain/risk').
