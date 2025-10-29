#!/usr/bin/env python3
"""
AST Code Manipulator - Method Stubber

This script demonstrates how to:
1. Parse source code into AST
2. Manipulate the AST (stub methods)
3. Generate modified source code back

It creates stubbed versions of Java and Kotlin classes.
"""

from tree_sitter import Language, Parser
import os
import re

class JavaCodeStubber:
    def __init__(self, java_language):
        self.java_language = java_language
        self.parser = Parser()
        self.parser.set_language(java_language)
    
    def stub_java_methods(self, source_code):
        """
        Parse Java code and return a stubbed version
        """
        tree = self.parser.parse(source_code.encode())
        
        # We'll build the new code by replacing method bodies
        modified_code = source_code
        
        # Find all methods and collect their body locations (in reverse order to maintain positions)
        methods_to_stub = []
        self._find_methods_recursive(tree.root_node, source_code, methods_to_stub)
        
        # Debug: Print method information
        print(f"Found {len(methods_to_stub)} methods to stub:")
        for i, method in enumerate(methods_to_stub):
            print(f"  {i+1}. {method['name']}() -> {method['return_type']} (body: {method['body_start']}-{method['body_end']})")
        
        # Sort by start position in reverse order so we can replace from end to beginning
        methods_to_stub.sort(key=lambda x: x['body_start'], reverse=True)
        
        # Replace each method body with a stub
        for method in methods_to_stub:
            if method['body_start'] is not None and method['body_end'] is not None:
                # Generate stub body
                stub_body = self._generate_java_stub_body(method)
                
                # Replace the method body in the source code
                before = modified_code[:method['body_start']]
                after = modified_code[method['body_end']:]
                modified_code = before + stub_body + after
        
        return modified_code
    
    def _find_methods_recursive(self, node, source_code, methods_list):
        """Recursively find all method declarations"""
        if node.type == 'method_declaration':
            method_info = self._extract_method_info(node, source_code)
            if method_info:
                methods_list.append(method_info)
        
        for child in node.children:
            self._find_methods_recursive(child, source_code, methods_list)
    
    def _extract_method_info(self, method_node, source_code):
        """Extract method information from a method_declaration node"""
        method_info = {
            'name': 'unknown',
            'return_type': 'void',
            'parameters': [],
            'modifiers': [],
            'body_start': None,
            'body_end': None
        }
        
        # Track if we've found a return type yet
        found_return_type = False
        
        for child in method_node.children:
            if child.type == 'modifiers':
                for mod_child in child.children:
                    if mod_child.type in ['public', 'private', 'protected', 'static', 'final', 'abstract']:
                        method_info['modifiers'].append(source_code[mod_child.start_byte:mod_child.end_byte])
            
            elif child.type in ['integral_type', 'floating_point_type', 'boolean_type']:
                method_info['return_type'] = source_code[child.start_byte:child.end_byte]
                found_return_type = True
            elif child.type == 'type_identifier':
                method_info['return_type'] = source_code[child.start_byte:child.end_byte]
                found_return_type = True
            elif child.type == 'void_type':
                method_info['return_type'] = 'void'
                found_return_type = True
            elif child.type == 'generic_type':
                method_info['return_type'] = source_code[child.start_byte:child.end_byte]
                found_return_type = True
            elif child.type == 'array_type':  # Added array type detection
                method_info['return_type'] = source_code[child.start_byte:child.end_byte]
                found_return_type = True
            elif child.type == 'scoped_type_identifier':  # For types like MediaBrowserCompat.MediaItem
                method_info['return_type'] = source_code[child.start_byte:child.end_byte]
                found_return_type = True
            
            elif child.type == 'identifier':
                # Only set as method name if we haven't found a return type yet
                # (to avoid confusing return type identifiers with method names)
                if found_return_type:
                    method_info['name'] = source_code[child.start_byte:child.end_byte]
                else:
                    # This might be a return type identifier we missed
                    method_info['return_type'] = source_code[child.start_byte:child.end_byte]
            
            elif child.type == 'formal_parameters':
                method_info['parameters'] = self._extract_parameters(child, source_code)
            
            elif child.type == 'block':
                method_info['body_start'] = child.start_byte
                method_info['body_end'] = child.end_byte
        
        # Fallback: if we still haven't found the method name, scan again more carefully
        if method_info['name'] == 'unknown':
            method_info['name'] = self._extract_method_name_fallback(method_node, source_code)
        
        return method_info
    
    def _extract_method_name_fallback(self, method_node, source_code):
        """Fallback method to extract method name when primary extraction fails"""
        # Look for identifier nodes that come after the return type
        identifiers = []
        
        def find_identifiers(node):
            if node.type == 'identifier':
                identifiers.append(source_code[node.start_byte:node.end_byte])
            for child in node.children:
                find_identifiers(child)
        
        find_identifiers(method_node)
        
        # The method name is typically the last identifier before parameters
        # or the first identifier that's not a known type
        known_types = ['public', 'private', 'protected', 'static', 'final', 'abstract', 
                      'int', 'long', 'boolean', 'String', 'void', 'MediaBrowserCompat', 'MediaItem']
        
        for identifier in reversed(identifiers):
            if identifier not in known_types:
                return identifier
        
        return 'unknown'
    
    def _extract_parameters(self, params_node, source_code):
        """Extract parameter information"""
        parameters = []
        
        for child in params_node.children:
            if child.type == 'formal_parameter':
                param_type = ''
                param_name = ''
                
                for p_child in child.children:
                    if p_child.type in ['integral_type', 'floating_point_type', 'boolean_type', 'type_identifier']:
                        param_type = source_code[p_child.start_byte:p_child.end_byte]
                    elif p_child.type == 'generic_type':
                        param_type = source_code[p_child.start_byte:p_child.end_byte]
                    elif p_child.type == 'array_type':
                        param_type = source_code[p_child.start_byte:p_child.end_byte]
                    elif p_child.type == 'identifier':
                        param_name = source_code[p_child.start_byte:p_child.end_byte]
                
                if param_type and param_name:
                    parameters.append({'type': param_type, 'name': param_name})
        
        return parameters
    
    def _is_array_type(self, type_str):
        """Check if a type string represents an array"""
        return type_str.endswith('[]') or '[]' in type_str
    
    def _get_array_component_type(self, array_type):
        """Extract the component type from an array type"""
        # Remove [] from the end and any whitespace
        component_type = array_type.replace('[]', '').strip()
        return component_type
    
    def _generate_array_creation(self, array_type, method_name):
        """Generate appropriate array creation code"""
        component_type = self._get_array_component_type(array_type)
        
        # Special case for newArray methods - they should create arrays of specified size
        if method_name == 'newArray':
            return f"return new {component_type}[size];"
        
        # For other array methods, return empty array
        return f"return new {component_type}[0];"
    
    def _generate_java_stub_body(self, method_info):
        """Generate appropriate stub body for Java method"""
        return_type = method_info['return_type'].strip()
        method_name = method_info['name']
        
        # Debug output
        print(f"Generating stub for {method_name}() with return type '{return_type}'")
        
        # Create indented stub body
        stub_lines = []
        stub_lines.append(" {")
        stub_lines.append(f"        // TODO: Implement {method_name}")
        
        # Add appropriate return statement
        if return_type == 'void':
            stub_lines.append("        // Method implementation goes here")
        elif return_type in ['int', 'long', 'short', 'byte']:
            stub_lines.append("        return 0;")
        elif return_type == 'float':
            stub_lines.append("        return 0.0f;")  # Float literal needs 'f' suffix
        elif return_type == 'double':
            stub_lines.append("        return 0.0;")
        elif return_type == 'boolean':
            stub_lines.append("        return false;")
        elif return_type == 'char':
            stub_lines.append("        return '\\0';")
        elif return_type == 'String':
            stub_lines.append("        return \"\";")
        elif self._is_array_type(return_type):
            # Handle array types properly
            array_creation = self._generate_array_creation(return_type, method_name)
            stub_lines.append(f"        {array_creation}")
        else:
            # For all other reference types (including generic types, complex types, unknown types)
            # Always add a return null to be safe
            stub_lines.append("        return null;")
        
        stub_lines.append("    }")
        
        return '\n'.join(stub_lines)

class KotlinCodeStubber:
    def __init__(self, kotlin_language):
        self.kotlin_language = kotlin_language
        self.parser = Parser()
        self.parser.set_language(kotlin_language)
    
    def stub_kotlin_functions(self, source_code):
        """
        Parse Kotlin code and return a stubbed version
        """
        tree = self.parser.parse(source_code.encode())
        
        # We'll build the new code by replacing function bodies
        modified_code = source_code
        
        # Find all functions and collect their body locations
        functions_to_stub = []
        self._find_functions_recursive(tree.root_node, source_code, functions_to_stub)
        
        # Filter out functions without bodies (interfaces, abstract methods)
        functions_to_stub = [f for f in functions_to_stub if f['body_start'] is not None and f['body_end'] is not None]
        
        # Sort by start position in reverse order
        functions_to_stub.sort(key=lambda x: x['body_start'], reverse=True)
        
        # Replace each function body with a stub
        for function in functions_to_stub:
            # Generate stub body
            stub_body = self._generate_kotlin_stub_body(function)
            
            # Replace the function body in the source code
            before = modified_code[:function['body_start']]
            after = modified_code[function['body_end']:]
            modified_code = before + stub_body + after
        
        return modified_code
    
    def _find_functions_recursive(self, node, source_code, functions_list):
        """Recursively find all function declarations"""
        if node.type == 'function_declaration':
            function_info = self._extract_function_info(node, source_code)
            if function_info:
                functions_list.append(function_info)
        
        for child in node.children:
            self._find_functions_recursive(child, source_code, functions_list)
    
    def _extract_function_info(self, func_node, source_code):
        """Extract function information from a function_declaration node"""
        func_info = {
            'name': 'unknown',
            'return_type': 'Unit',
            'parameters': [],
            'modifiers': [],
            'body_start': None,
            'body_end': None,
            'is_suspend': False
        }
        
        for child in func_node.children:
            if child.type == 'modifiers':
                for mod_child in child.children:
                    modifier = source_code[mod_child.start_byte:mod_child.end_byte]
                    func_info['modifiers'].append(modifier)
                    if modifier == 'suspend':
                        func_info['is_suspend'] = True
            
            elif child.type == 'simple_identifier':
                func_info['name'] = source_code[child.start_byte:child.end_byte]
            
            elif child.type == 'function_value_parameters':
                func_info['parameters'] = self._extract_kotlin_parameters(child, source_code)
            
            elif child.type in ['user_type', 'type_identifier', 'nullable_type']:  # Added nullable_type
                func_info['return_type'] = source_code[child.start_byte:child.end_byte]
            
            elif child.type == 'function_body':
                func_info['body_start'] = child.start_byte
                func_info['body_end'] = child.end_byte
        
        return func_info
    
    def _extract_kotlin_parameters(self, params_node, source_code):
        """Extract Kotlin parameter information"""
        parameters = []
        
        for child in params_node.children:
            if child.type == 'parameter':
                param_name = ''
                param_type = ''
                
                for p_child in child.children:
                    if p_child.type == 'simple_identifier':
                        param_name = source_code[p_child.start_byte:p_child.end_byte]
                    elif p_child.type in ['user_type', 'type_identifier']:
                        param_type = source_code[p_child.start_byte:p_child.end_byte]
                
                if param_name:
                    parameters.append({'name': param_name, 'type': param_type or 'Any'})
        
        return parameters
    
    def _is_array_type_kotlin(self, type_str):
        """Check if a Kotlin type string represents an array"""
        return type_str.startswith('Array<') or type_str.endswith('Array')
    
    def _generate_kotlin_stub_body(self, func_info):
        """Generate appropriate stub body for Kotlin function"""
        return_type = func_info['return_type']
        func_name = func_info['name']
        
        # Create indented stub body
        stub_lines = []
        stub_lines.append(" {")
        stub_lines.append(f"        // TODO: Implement {func_name}")
        
        # Determine if this is a nullable type
        is_nullable = return_type.endswith('?')
        base_type = return_type.rstrip('?').strip()
        
        # Add appropriate return statement
        if return_type == 'Unit' or return_type == '':
            stub_lines.append("        // Function implementation goes here")
        elif base_type in ['Int', 'Long', 'Short', 'Byte']:
            if is_nullable:
                stub_lines.append("        return null")
            else:
                stub_lines.append("        return 0")
        elif base_type in ['Float', 'Double']:
            if is_nullable:
                stub_lines.append("        return null")
            else:
                stub_lines.append("        return 0.0")
        elif base_type == 'Boolean':
            if is_nullable:
                stub_lines.append("        return null")
            else:
                stub_lines.append("        return false")
        elif base_type == 'String':
            if is_nullable:
                stub_lines.append("        return null")
            else:
                stub_lines.append("        return \"\"")
        elif self._is_array_type_kotlin(base_type):
            # Handle Kotlin arrays
            if is_nullable:
                stub_lines.append("        return null")
            elif func_name == 'newArray':
                stub_lines.append("        return arrayOfNulls(size)")
            else:
                stub_lines.append("        return emptyArray()")
        elif is_nullable:
            # Nullable types - return null
            stub_lines.append("        return null")
        else:
            # Non-nullable reference types - try to construct or throw
            # Use error() which throws IllegalStateException - this compiles and is idiomatic Kotlin
            stub_lines.append(f"        error(\"Not yet implemented: {func_name}\")")
        
        stub_lines.append("    }")
        
        return '\n'.join(stub_lines)