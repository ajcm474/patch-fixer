#!/usr/bin/env python3
import argparse
import ast
import sys
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Any
from pathlib import Path
from colorama import init, Fore, Style

# Initialize colorama for cross-platform colored output
init()

@dataclass
class Complexity:
    expression: str
    is_approximate: bool = False
    details: List[str] = field(default_factory=list)
    
    @classmethod
    def constant(cls):
        return cls("O(1)", False, [])
    
    @classmethod
    def linear(cls, coefficient: int = 1):
        expr = f"O({coefficient}n)" if coefficient != 1 else "O(n)"
        return cls(expr, False, [])
    
    @classmethod
    def approximate(cls, expr: str):
        return cls(expr, True, [])
    
    def with_detail(self, detail: str):
        self.details.append(detail)
        return self
    
    def combine_sequential(self, other: 'Complexity') -> 'Complexity':
        """For sequential operations, we add complexities"""
        is_approx = self.is_approximate or other.is_approximate
        details = self.details + other.details
        
        # Don't add O(1) unless both are O(1)
        if self.expression == "O(1)" and other.expression == "O(1)":
            expr = "O(1)"
        elif self.expression == "O(1)":
            expr = other.expression
        elif other.expression == "O(1)":
            expr = self.expression
        else:
            expr = f"{self.expression}+{other.expression}"
        
        return Complexity(expr, is_approx, details)
    
    def combine_nested(self, other: 'Complexity') -> 'Complexity':
        """For nested operations, we multiply complexities"""
        is_approx = self.is_approximate or other.is_approximate
        details = self.details + other.details
        
        if self.expression == "O(1)":
            expr = other.expression
        elif other.expression == "O(1)":
            expr = self.expression
        else:
            expr = f"{self.expression}*{other.expression}"
        
        return Complexity(expr, is_approx, details)
    
    def max(self, other: 'Complexity') -> 'Complexity':
        """Return the maximum complexity (for if/else branches)"""
        # For branches, we should take the worse case
        # This is a simplified comparison
        self_weight = self._get_weight()
        other_weight = other._get_weight()
        
        if self_weight >= other_weight:
            return self
        else:
            return other
    
    def _get_weight(self) -> int:
        """Get a rough weight for complexity comparison"""
        expr = self.expression
        if 'n⁴' in expr or 'n^4' in expr:
            return 4
        elif 'n³' in expr or 'n^3' in expr:
            return 3
        elif 'n²' in expr or 'n^2' in expr:
            return 2
        elif 'n*log' in expr:
            return 1.5
        elif 'n' in expr:
            return 1
        elif 'log' in expr:
            return 0.5
        else:
            return 0
    
    def simplify(self) -> 'Complexity':
        """Simplify the complexity expression WITHOUT reducing to dominant term"""
        expr = self.expression
        
        # Handle nested multiplications (convert to exponents)
        if '*' in expr:
            parts = []
            current = ""
            depth = 0
            
            for char in expr:
                if char == '(':
                    depth += 1
                    current += char
                elif char == ')':
                    depth -= 1
                    current += char
                elif char == '*' and depth == 0:
                    parts.append(current)
                    current = ""
                else:
                    current += char
            
            if current:
                parts.append(current)
            
            # Count O(n) occurrences
            n_count = sum(1 for p in parts if p == "O(n)")
            other_parts = [p for p in parts if p != "O(n)" and p != "O(1)"]
            
            if n_count >= 2:
                power_notation = {2: "²", 3: "³", 4: "⁴"}
                if n_count in power_notation:
                    result = f"O(n{power_notation[n_count]})"
                else:
                    result = f"O(n^{n_count})"
                
                # Add other multiplicative factors
                for part in other_parts:
                    if "log" in part:
                        result = result.replace(")", "*log(n))")
                    elif part and part != "O(1)":
                        result = f"{result}*{part}"
                
                expr = result
            elif n_count == 1:
                # Single O(n) with other factors
                result = "O(n)"
                for part in other_parts:
                    if "log" in part:
                        result = "O(n*log(n))"
                    elif part and part != "O(1)":
                        result = f"{result}*{part}"
                expr = result
        
        # Clean up redundant O(1) in additions, but keep all other terms
        if '+' in expr:
            parts = expr.split('+')
            # Remove O(1) only if there are other non-constant terms
            non_constant = [p for p in parts if p != "O(1)"]
            if non_constant:
                expr = '+'.join(non_constant)
            else:
                expr = "O(1)"
        
        # If empty, return O(1)
        if not expr:
            expr = "O(1)"
        
        return Complexity(expr, self.is_approximate, self.details)

@dataclass
class AntiPattern:
    line: int
    pattern_type: str
    description: str

@dataclass
class FunctionAnalysis:
    name: str
    complexity: Complexity
    anti_patterns: List[AntiPattern]

class Analyzer(ast.NodeVisitor):
    def __init__(self):
        self.functions: Dict[str, Complexity] = {}
        self.variable_types: Dict[str, str] = {}
        self.call_stack: List[str] = []  # Track call stack for recursion
        self.max_call_depth = 3
        self.current_class = None
        self.results: List[FunctionAnalysis] = []
        self.anti_patterns: List[AntiPattern] = []
        
    def analyze_file(self, content: str, filename: str = "<file>") -> List[FunctionAnalysis]:
        """Analyze Python file content"""
        try:
            tree = ast.parse(content, filename)
        except SyntaxError as e:
            raise ValueError(f"Parse error: {e}")
        
        self.visit(tree)
        return self.results
    
    def visit_ClassDef(self, node: ast.ClassDef):
        """Visit class definition"""
        old_class = self.current_class
        self.current_class = node.name
        self.generic_visit(node)
        self.current_class = old_class
    
    def visit_FunctionDef(self, node: ast.FunctionDef):
        """Visit function definition"""
        self.anti_patterns = []
        self.variable_types.clear()
        self.call_stack = []  # Reset call stack for each function
        
        # Extract type annotations from parameters
        for arg in node.args.args:
            if arg.annotation:
                if isinstance(arg.annotation, ast.Subscript):
                    # Handle List[int], Dict[str, int], etc.
                    if isinstance(arg.annotation.value, ast.Name):
                        self.variable_types[arg.arg] = arg.annotation.value.id
                elif isinstance(arg.annotation, ast.Name):
                    self.variable_types[arg.arg] = arg.annotation.id
        
        # Analyze function body
        complexity = self.analyze_body(node.body)
        
        # Store function name with class prefix if in a class
        if self.current_class:
            func_name = f"{self.current_class}.{node.name}"
        else:
            func_name = node.name
        
        self.functions[func_name] = complexity
        
        analysis = FunctionAnalysis(
            name=func_name,
            complexity=complexity,
            anti_patterns=self.anti_patterns.copy()
        )
        self.results.append(analysis)
        
        # Don't visit nested functions
        return
    
    visit_AsyncFunctionDef = visit_FunctionDef
    
    def analyze_body(self, body: List[ast.stmt]) -> Complexity:
        """Analyze a list of statements"""
        total = Complexity.constant()
        
        for stmt in body:
            stmt_complexity = self.analyze_statement(stmt)
            total = total.combine_sequential(stmt_complexity)
        
        return total.simplify()
    
    def analyze_statement(self, stmt: ast.stmt) -> Complexity:
        """Analyze a single statement"""
        if isinstance(stmt, ast.For):
            return self.analyze_for_loop(stmt)
        elif isinstance(stmt, ast.While):
            return self.analyze_while_loop(stmt)
        elif isinstance(stmt, ast.If):
            return self.analyze_if(stmt)
        elif isinstance(stmt, (ast.Return, ast.Expr)):
            if isinstance(stmt, ast.Return) and stmt.value:
                return self.analyze_expr(stmt.value)
            elif isinstance(stmt, ast.Expr):
                return self.analyze_expr(stmt.value)
            return Complexity.constant()
        elif isinstance(stmt, (ast.Assign, ast.AugAssign, ast.AnnAssign)):
            if isinstance(stmt, ast.Assign):
                return self.analyze_expr(stmt.value)
            elif isinstance(stmt, ast.AugAssign):
                return self.analyze_expr(stmt.value)
            elif isinstance(stmt, ast.AnnAssign) and stmt.value:
                return self.analyze_expr(stmt.value)
            return Complexity.constant()
        else:
            return Complexity.constant()
    
    def analyze_for_loop(self, node: ast.For) -> Complexity:
        """Analyze for loop complexity"""
        iter_complexity = self.estimate_iteration_count(node.iter)
        body_complexity = self.analyze_body(node.body)
        
        combined = iter_complexity.combine_nested(body_complexity)
        return combined.with_detail("for loop").simplify()
    
    def analyze_while_loop(self, node: ast.While) -> Complexity:
        """Analyze while loop complexity"""
        body_complexity = self.analyze_body(node.body)
        
        # While loops have unknown iterations in static analysis
        if body_complexity.expression == "O(1)":
            result = Complexity.linear(1)
        else:
            result = body_complexity.combine_nested(Complexity.linear(1))
            result.is_approximate = True
        
        return result.with_detail("while loop (unknown iterations)").simplify()
    
    def analyze_if(self, node: ast.If) -> Complexity:
        """Analyze if statement - take max of branches"""
        if_body = self.analyze_body(node.body)
        else_body = self.analyze_body(node.orelse)
        return if_body.max(else_body)
    
    def estimate_iteration_count(self, iter_node: ast.expr) -> Complexity:
        """Estimate iteration count for loop iterator"""
        if isinstance(iter_node, ast.Call):
            if isinstance(iter_node.func, ast.Name):
                if iter_node.func.id == 'range':
                    return Complexity.linear(1)
                elif iter_node.func.id in ('enumerate', 'zip'):
                    # These iterate over their arguments
                    if iter_node.args:
                        return self.estimate_iteration_count(iter_node.args[0])
                    return Complexity.linear(1)
            return Complexity.approximate("O(n)")
        elif isinstance(iter_node, (ast.Name, ast.Attribute)):
            return Complexity.linear(1)
        elif isinstance(iter_node, (ast.List, ast.Tuple)):
            # Literal list/tuple - count elements
            return Complexity.linear(1)
        else:
            return Complexity.approximate("O(n)")
    
    def analyze_expr(self, expr: ast.expr) -> Complexity:
        """Analyze expression complexity"""
        if isinstance(expr, (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)):
            return self.analyze_comprehension(expr)
        elif isinstance(expr, ast.Call):
            return self.analyze_call(expr)
        elif isinstance(expr, ast.Compare):
            return self.analyze_compare(expr)
        elif isinstance(expr, ast.Lambda):
            # Analyze lambda body as expression
            return self.analyze_expr(expr.body)
        elif isinstance(expr, ast.List):
            total = Complexity.constant()
            for el in expr.elts:
                total = total.combine_sequential(self.analyze_expr(el))
            return total
        else:
            return Complexity.constant()
    
    def analyze_comprehension(self, node) -> Complexity:
        """Analyze list/set/dict comprehension or generator expression"""
        complexity = Complexity.constant()
        
        for generator in node.generators:
            iter_complexity = self.estimate_iteration_count(generator.iter)
            complexity = complexity.combine_nested(iter_complexity)
        
        # Check for anti-pattern (using list comp where generator would work)
        if isinstance(node, ast.ListComp):
            self.anti_patterns.append(AntiPattern(
                line=node.lineno,
                pattern_type="list_comprehension",
                description="List comprehension could potentially be replaced with generator expression for memory efficiency"
            ))
        
        return complexity.with_detail("comprehension").simplify()
    
    def analyze_call(self, node: ast.Call) -> Complexity:
        """Analyze function call complexity"""
        if isinstance(node.func, ast.Name):
            func_name = node.func.id
            
            # Built-in functions with known complexity
            complexity_map = {
                'len': Complexity.constant(),
                'print': Complexity.constant(),
                'sum': Complexity.linear(1),
                'max': Complexity.linear(1),
                'min': Complexity.linear(1),
                'sorted': Complexity("O(n*log(n))", False),
                'reversed': Complexity.linear(1),
                'enumerate': Complexity.constant(),
                'zip': Complexity.constant(),
                'map': Complexity.constant(),
                'filter': Complexity.constant(),
                'list': Complexity.linear(1) if node.args else Complexity.constant(),
                'set': Complexity.linear(1) if node.args else Complexity.constant(),
                'dict': Complexity.constant(),
                'all': Complexity.linear(1),
                'any': Complexity.linear(1),
            }
            
            if func_name in complexity_map:
                complexity = complexity_map[func_name]
            elif func_name in self.functions:
                # Check recursion depth
                if func_name in self.call_stack:
                    # Already in call stack - check depth
                    depth = self.call_stack.count(func_name)
                    if depth >= self.max_call_depth:
                        complexity = Complexity.approximate("O(?)")
                        complexity.with_detail(f"max recursion depth {self.max_call_depth} reached for {func_name}")
                    else:
                        # Allow the recursive call but track it
                        self.call_stack.append(func_name)
                        complexity = self.functions[func_name]
                        self.call_stack.pop()
                else:
                    # First call to this function
                    self.call_stack.append(func_name)
                    complexity = self.functions[func_name]
                    self.call_stack.pop()
            else:
                complexity = Complexity.approximate("O(?)")
                complexity.with_detail(f"unknown function: {func_name}")
            
            # Analyze arguments
            for arg in node.args:
                arg_complexity = self.analyze_expr(arg)
                complexity = complexity.combine_sequential(arg_complexity)
            
            return complexity
            
        elif isinstance(node.func, ast.Attribute):
            return self.analyze_method_call(node.func)
        else:
            return Complexity.approximate("O(?)")
    
    def analyze_method_call(self, attr: ast.Attribute) -> Complexity:
        """Analyze method call complexity"""
        method_complexity = {
            'append': Complexity.constant(),
            'pop': Complexity.constant(),
            'insert': Complexity.linear(1),
            'remove': Complexity.linear(1),
            'sort': Complexity("O(n*log(n))", False),
            'index': Complexity.linear(1),
            'count': Complexity.linear(1),
            'extend': Complexity.linear(1),
            'copy': Complexity.linear(1),
            'clear': Complexity.constant(),
            'get': Complexity.constant(),
            'items': Complexity.linear(1),
            'keys': Complexity.linear(1),
            'values': Complexity.linear(1),
            'update': Complexity.linear(1),
            'add': Complexity.constant(),  # set.add
            'discard': Complexity.constant(),  # set.discard
            'union': Complexity.linear(1),
            'intersection': Complexity.linear(1),
            'difference': Complexity.linear(1),
        }
        
        return method_complexity.get(attr.attr, Complexity.approximate("O(?)")).simplify()
    
    def analyze_compare(self, node: ast.Compare) -> Complexity:
        """Analyze comparison operations"""
        for i, op in enumerate(node.ops):
            if isinstance(op, (ast.In, ast.NotIn)):
                if i < len(node.comparators):
                    comparator = node.comparators[i]
                    
                    if isinstance(comparator, ast.List):
                        # List literal membership test - always O(n)
                        self.anti_patterns.append(AntiPattern(
                            line=node.lineno,
                            pattern_type="list_membership",
                            description="Membership test with list literal - use set for O(1) lookup instead of O(n)"
                        ))
                        return Complexity.linear(1).with_detail("list membership check")
                    
                    elif isinstance(comparator, ast.Set):
                        # Set literal membership test - O(1)
                        return Complexity.constant().with_detail("set membership check")
                    
                    elif isinstance(comparator, ast.Name):
                        # Check variable type if known
                        var_type = self.variable_types.get(comparator.id)
                        if var_type in ('List', 'list'):
                            self.anti_patterns.append(AntiPattern(
                                line=node.lineno,
                                pattern_type="membership_check",
                                description="Membership test with List type - consider using Set for O(1) lookup instead of O(n)"
                            ))
                            return Complexity.linear(1).with_detail("list membership check")
                        elif var_type in ('Set', 'set', 'Dict', 'dict'):
                            return Complexity.constant().with_detail("set/dict membership check")
                        else:
                            # Unknown type - assume worst case (list)
                            self.anti_patterns.append(AntiPattern(
                                line=node.lineno,
                                pattern_type="membership_check",
                                description="Membership test with unknown type - if this is a list, consider using set for O(1) lookup"
                            ))
                            return Complexity.approximate("O(n)").with_detail("membership check (unknown type)")
                    
                    elif isinstance(comparator, ast.Attribute):
                        # Accessing an attribute - assume list for worst case
                        self.anti_patterns.append(AntiPattern(
                            line=node.lineno,
                            pattern_type="membership_check",
                            description="Membership test with unknown type - if this is a list, consider using set for O(1) lookup"
                        ))
                        return Complexity.approximate("O(n)").with_detail("membership check (unknown type)")
        
        return Complexity.constant()

def main():
    parser = argparse.ArgumentParser(
        description="Analyze algorithmic complexity of Python code"
    )
    parser.add_argument('file', type=Path, help='Python file to analyze')
    parser.add_argument('-v', '--verbose', action='store_true', 
                       help='Show detailed analysis')
    
    args = parser.parse_args()
    
    try:
        content = args.file.read_text()
    except Exception as e:
        print(f"{Fore.RED}{Style.BRIGHT}Error:{Style.RESET_ALL} Failed to read file: {e}")
        sys.exit(1)
    
    analyzer = Analyzer()
    
    try:
        results = analyzer.analyze_file(content, str(args.file))
    except ValueError as e:
        print(f"{Fore.RED}{Style.BRIGHT}Analysis failed:{Style.RESET_ALL} {e}")
        sys.exit(1)
    
    # Print results
    print(f"\n{Fore.CYAN}{'═' * 80}{Style.RESET_ALL}")
    print(f"{Fore.CYAN}{Style.BRIGHT}  Python Complexity Analysis: {args.file}{Style.RESET_ALL}")
    print(f"{Fore.CYAN}{'═' * 80}{Style.RESET_ALL}\n")
    
    has_approximate = any(r.complexity.is_approximate for r in results)
    
    for analysis in results:
        approx_marker = " *" if analysis.complexity.is_approximate else ""
        
        print(f"{Fore.GREEN}{Style.BRIGHT}Function/Method:{Style.RESET_ALL} {Fore.YELLOW}{analysis.name}{Style.RESET_ALL}")
        print(f"  {Fore.BLUE}{Style.BRIGHT}Complexity:{Style.RESET_ALL} {Fore.MAGENTA}{analysis.complexity.expression}{Style.RESET_ALL}{Fore.RED}{Style.BRIGHT}{approx_marker}{Style.RESET_ALL}")
        
        if args.verbose and analysis.complexity.details:
            print(f"  {Fore.BLUE}{Style.BRIGHT}Details:{Style.RESET_ALL}")
            for detail in analysis.complexity.details:
                print(f"    - {detail}")
        
        if analysis.anti_patterns:
            print(f"  {Fore.YELLOW}{Style.BRIGHT}⚠ Performance Issues:{Style.RESET_ALL}")
            for ap in analysis.anti_patterns:
                print(f"    {Fore.RED}•{Style.RESET_ALL} [line {ap.line}]: {Fore.YELLOW}{ap.description}{Style.RESET_ALL}")
        
        print()
    
    if has_approximate:
        print(f"{Fore.YELLOW}{Style.BRIGHT}Note:{Style.RESET_ALL} {Fore.RED}{Style.BRIGHT}*{Style.RESET_ALL} Complexity marked with * is approximate due to static analysis limitations")

if __name__ == "__main__":
    main()
