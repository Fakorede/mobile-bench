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
        
        # Sort by start position in reverse order
        functions_to_stub.sort(key=lambda x: x['body_start'], reverse=True)
        
        # Replace each function body with a stub
        for function in functions_to_stub:
            if function['body_start'] is not None and function['body_end'] is not None:
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
            
            elif child.type in ['user_type', 'type_identifier']:
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
        
        # Add appropriate return statement
        if return_type == 'Unit' or return_type == '':
            stub_lines.append("        // Function implementation goes here")
        elif return_type in ['Int', 'Long', 'Short', 'Byte']:
            stub_lines.append("        return 0")
        elif return_type in ['Float', 'Double']:
            stub_lines.append("        return 0.0")
        elif return_type == 'Boolean':
            stub_lines.append("        return false")
        elif return_type == 'String':
            stub_lines.append("        return \"\"")
        elif self._is_array_type_kotlin(return_type):
            # Handle Kotlin arrays
            if func_name == 'newArray':
                stub_lines.append("        return arrayOfNulls(size)")
            else:
                stub_lines.append("        return emptyArray()")
        else:
            stub_lines.append("        TODO(\"Not yet implemented\")")
        
        stub_lines.append("    }")
        
        return '\n'.join(stub_lines)

# def demo_java_stubbing():
#     """Demonstrate Java code stubbing"""
#     print("=" * 70)
#     print("🔧 Java Code Stubbing Demo")
#     print("=" * 70)
    
#     # Load Java language
#     java_language = Language('./build/java-language.so', 'java')
#     stubber = JavaCodeStubber(java_language)
    
#     # Original Java code
#     original_code = '''public class Calculator {
#     public int add(int a, int b) {
#         int result = a + b;
#         System.out.println("Adding " + a + " + " + b + " = " + result);
#         return result;
#     }
    
#     public double multiply(double x, double y) {
#         double product = x * y;
#         logOperation("multiply");
#         return product;
#     }
    
#     private boolean isValid(String input) {
#         if (input == null) {
#             return false;
#         }
#         return !input.trim().isEmpty();
#     }
    
#     protected void logOperation(String operation) {
#         System.out.println("Performing operation: " + operation);
#         // Log to file or database
#     }
    
#     public static String formatResult(double result) {
#         return String.format("Result: %.2f", result);
#     }
# }'''
    
#     print("📄 Original Java Code:")
#     print("-" * 50)
#     print(original_code)
#     print()
    
#     # Generate stubbed version
#     stubbed_code = stubber.stub_java_methods(original_code)
    
#     print("🎯 Stubbed Java Code:")
#     print("-" * 50)
#     print(stubbed_code)
#     print()

# def demo_kotlin_stubbing():
#     """Demonstrate Kotlin code stubbing"""
#     print("=" * 70)
#     print("🔧 Kotlin Code Stubbing Demo")
#     print("=" * 70)
    
#     # Load Kotlin language
#     kotlin_language = Language('./build/kotlin-language.so', 'kotlin')
#     stubber = KotlinCodeStubber(kotlin_language)
    
#     # Original Kotlin code
#     original_code = '''class Calculator {
#     fun add(a: Int, b: Int): Int {
#         val result = a + b
#         println("Adding $a + $b = $result")
#         return result
#     }
    
#     fun multiply(x: Double, y: Double): Double {
#         val product = x * y
#         logOperation("multiply")
#         return product
#     }
    
#     private fun isValid(input: String): Boolean {
#         return input.isNotBlank()
#     }
    
#     protected fun logOperation(operation: String) {
#         println("Performing operation: $operation")
#         // Log to file or database
#     }
    
#     suspend fun fetchData(url: String): String {
#         // Simulate network call
#         delay(1000)
#         return "Data from $url"
#     }
    
#     companion object {
#         fun formatResult(result: Double): String {
#             return "Result: %.2f".format(result)
#         }
#     }
# }'''
    
#     print("📄 Original Kotlin Code:")
#     print("-" * 50)
#     print(original_code)
#     print()
    
#     # Generate stubbed version
#     stubbed_code = stubber.stub_kotlin_functions(original_code)
    
#     print("🎯 Stubbed Kotlin Code:")
#     print("-" * 50)
#     print(stubbed_code)
#     print()

# def save_stubbed_files():
#     """Save stubbed versions to files"""
#     print("=" * 70)
#     print("💾 Saving Stubbed Files")
#     print("=" * 70)
    
#     # Java example
#     java_language = Language('./build/java-language.so', 'java')
#     java_stubber = JavaCodeStubber(java_language)
    
#     java_original = '''public class ApiService {
#     public User getUserById(String userId) throws UserNotFoundException {
#         // Database lookup
#         User user = database.findUser(userId);
#         if (user == null) {
#             throw new UserNotFoundException("User not found: " + userId);
#         }
#         return user;
#     }
    
#     public boolean updateUser(User user) {
#         try {
#             database.saveUser(user);
#             return true;
#         } catch (Exception e) {
#             logger.error("Failed to update user", e);
#             return false;
#         }
#     }
    
#     public List<User> getAllUsers() {
#         return database.getAllUsers();
#     }
# }'''
    
#     java_stubbed = java_stubber.stub_java_methods(java_original)
    
#     # Save Java files
#     with open('ApiService_original.java', 'w') as f:
#         f.write(java_original)
#     with open('ApiService_stubbed.java', 'w') as f:
#         f.write(java_stubbed)
    
#     print("✅ Saved Java files:")
#     print("   - ApiService_original.java")
#     print("   - ApiService_stubbed.java")
    
#     # Kotlin example
#     kotlin_language = Language('./build/kotlin-language.so', 'kotlin')
#     kotlin_stubber = KotlinCodeStubber(kotlin_language)
    
#     kotlin_original = '''class UserRepository {
#     suspend fun getUser(id: String): User? {
#         return withContext(Dispatchers.IO) {
#             database.findUserById(id)
#         }
#     }
    
#     suspend fun saveUser(user: User): Boolean {
#         return try {
#             database.insertOrUpdate(user)
#             true
#         } catch (e: Exception) {
#             false
#         }
#     }
    
#     fun validateUser(user: User): ValidationResult {
#         val errors = mutableListOf<String>()
        
#         if (user.name.isBlank()) {
#             errors.add("Name cannot be blank")
#         }
        
#         if (user.email.isBlank() || !user.email.contains("@")) {
#             errors.add("Invalid email")
#         }
        
#         return ValidationResult(errors.isEmpty(), errors)
#     }
# }'''
    
#     kotlin_stubbed = kotlin_stubber.stub_kotlin_functions(kotlin_original)
    
#     # Save Kotlin files
#     with open('UserRepository_original.kt', 'w') as f:
#         f.write(kotlin_original)
#     with open('UserRepository_stubbed.kt', 'w') as f:
#         f.write(kotlin_stubbed)
    
#     print("✅ Saved Kotlin files:")
#     print("   - UserRepository_original.kt")
#     print("   - UserRepository_stubbed.kt")
#     print()

# def main():
#     """Main demonstration function"""
#     if not (os.path.exists('./build/java-language.so') and os.path.exists('./build/kotlin-language.so')):
#         print("❌ Language libraries not found. Please run setup_treesitter.sh first.")
#         return
    
#     print("🚀 AST Code Manipulation Demo")
#     print("This demo shows how to parse, modify, and regenerate source code")
#     print()
    
#     # Run demos
#     demo_java_stubbing()
#     print("\n" + "=" * 80 + "\n")
#     demo_kotlin_stubbing()
#     print("\n" + "=" * 80 + "\n")
#     save_stubbed_files()
    
#     print("=" * 80)
#     print("✅ AST Code Manipulation Demo Complete!")
#     print()

# if __name__ == "__main__":
#     main()