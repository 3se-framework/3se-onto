% Closures over the facts of facts.pl: subclass, composition, related.
% Domain-neutral; used by the other rules of core/ and domain/.

:- dynamic sub_class_of/2, is_composed_of/2, related/2.

:- table sub_class_of_t/2, composed_of_t/2.

%! sub_class_of_t(?Sub, ?Super) is nondet.
%  Transitive closure of sub_class_of/2 (tabled, so cycles terminate).
sub_class_of_t(X, Y) :- sub_class_of(X, Y).
sub_class_of_t(X, Z) :- sub_class_of(X, Y), sub_class_of_t(Y, Z).

%! is_a(?X, ?Y) is nondet.
%  X is Y or a (transitive) subclass of Y.
is_a(X, X) :- term(X).
is_a(X, Y) :- sub_class_of_t(X, Y).

%! composed_of_t(?Whole, ?Part) is nondet.
%  Transitive closure of is_composed_of/2.
composed_of_t(X, Y) :- is_composed_of(X, Y).
composed_of_t(X, Z) :- is_composed_of(X, Y), composed_of_t(Y, Z).

%! linked(?X, ?Y) is nondet.
%  related/2 read as the symmetric relation it is.
linked(X, Y) :- related(X, Y).
linked(X, Y) :- related(Y, X).
