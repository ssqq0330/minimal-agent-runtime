"""Safe arithmetic calculator implemented with an AST allow-list."""

from __future__ import annotations

import ast
import math
import operator
from typing import Any, Callable, Dict

from app.tools.base import BaseTool, ToolContext, ToolResult


class CalculatorTool(BaseTool):
    """Calculate a restricted arithmetic expression without dynamic execution."""

    name = "calculator"
    description = "安全地计算数学表达式，支持加减乘除、乘方、取模和括号。"
    parameters_schema = {
        "type": "object",
        "properties": {
            "expression": {
                "type": "string",
                "description": "需要计算的数学表达式",
            }
        },
        "required": ["expression"],
        "additionalProperties": False,
    }

    _BINARY_OPERATORS: Dict[type, Callable[[Any, Any], Any]] = {
        ast.Add: operator.add,
        ast.Sub: operator.sub,
        ast.Mult: operator.mul,
        ast.Div: operator.truediv,
        ast.Pow: operator.pow,
        ast.Mod: operator.mod,
    }

    def execute(
        self,
        arguments: Dict[str, Any],
        context: ToolContext,
    ) -> ToolResult:
        """Evaluate an allow-listed mathematical expression."""
        validation_error = self.validate_arguments(arguments)
        if validation_error is not None:
            return validation_error

        expression = arguments["expression"]
        if len(expression) > 200:
            return ToolResult(False, None, "Expression must not exceed 200 characters.")

        try:
            parsed_expression = ast.parse(expression, mode="eval")
            result = self._evaluate(parsed_expression.body)
            self._ensure_finite(result)
        except SyntaxError:
            return ToolResult(False, None, "Invalid mathematical expression.")
        except ZeroDivisionError:
            return ToolResult(False, None, "Division by zero is not allowed.")
        except (ArithmeticError, TypeError, ValueError) as error:
            return ToolResult(False, None, "Invalid mathematical expression: {}".format(error))
        except Exception as error:
            return ToolResult(False, None, "Calculator failed: {}".format(error))

        return ToolResult(
            True,
            {"expression": expression, "result": result},
        )

    def _evaluate(self, node: ast.AST) -> Any:
        if isinstance(node, ast.Constant):
            if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
                raise ValueError("Only numeric constants are allowed")
            return node.value

        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            operand = self._evaluate(node.operand)
            return operand if isinstance(node.op, ast.UAdd) else -operand

        if isinstance(node, ast.BinOp) and type(node.op) in self._BINARY_OPERATORS:
            left = self._evaluate(node.left)
            right = self._evaluate(node.right)
            if isinstance(node.op, ast.Pow) and abs(right) > 100:
                raise ValueError("Exponent absolute value must not exceed 100")
            return self._BINARY_OPERATORS[type(node.op)](left, right)

        raise ValueError("Only arithmetic operators and numeric constants are allowed")

    @staticmethod
    def _ensure_finite(result: Any) -> None:
        if isinstance(result, bool) or not isinstance(result, (int, float)):
            raise ValueError("Result must be a real number")
        try:
            is_finite = math.isfinite(result)
        except OverflowError:
            is_finite = False
        if not is_finite:
            raise ValueError("Result must be finite")
