#!/bin/bash
#
# Tree-sitter Setup Script for Kotlin/Java AST Parsing
#
# This script sets up tree-sitter with Kotlin and Java grammars for
# accurate AST-based method parsing and stubbing.
#
# Usage:
#     ./setup_treesitter.sh [options]
#     
# Options:
#     --update        Update existing grammars to latest version
#     --no-venv       Skip virtual environment creation
#     --clean         Clean existing build artifacts first
#     --help          Show this help message
#
# Requirements:
#     - Python 3.7+
#     - Node.js (for building grammars)
#     - Git
#     - C compiler (gcc/clang)
#

set -e

# Color codes for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Default options
UPDATE_GRAMMARS=false
USE_VENV=true
CLEAN_BUILD=true

# Parse command line arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --update)
            UPDATE_GRAMMARS=true
            shift
            ;;
        --no-venv)
            USE_VENV=false
            shift
            ;;
        --clean)
            CLEAN_BUILD=true
            shift
            ;;
        --help)
            echo "Tree-sitter Setup Script for Kotlin/Java AST Parsing"
            echo ""
            echo "Usage: $0 [options]"
            echo ""
            echo "Options:"
            echo "  --update      Update existing grammars to latest version"
            echo "  --no-venv     Skip virtual environment creation"
            echo "  --clean       Clean existing build artifacts first"
            echo "  --help        Show this help message"
            exit 0
            ;;
        *)
            echo -e "${RED}❌ Unknown option: $1${NC}"
            echo "Use --help for usage information"
            exit 1
            ;;
    esac
done

# Logging functions
log_info() {
    echo -e "${BLUE}ℹ️  $1${NC}"
}

log_success() {
    echo -e "${GREEN}✅ $1${NC}"
}

log_warning() {
    echo -e "${YELLOW}⚠️  $1${NC}"
}

log_error() {
    echo -e "${RED}❌ $1${NC}"
}

# Check dependencies
check_dependencies() {
    log_info "Checking dependencies..."
    
    local missing_deps=()
    
    if ! command -v python3 >/dev/null 2>&1; then
        missing_deps+=("python3")
    fi
    
    if ! command -v git >/dev/null 2>&1; then
        missing_deps+=("git")
    fi
    
    if ! command -v node >/dev/null 2>&1; then
        missing_deps+=("node")
    fi
    
    # Check for C compiler
    if ! command -v gcc >/dev/null 2>&1 && ! command -v clang >/dev/null 2>&1; then
        missing_deps+=("gcc or clang")
    fi
    
    if [ ${#missing_deps[@]} -ne 0 ]; then
        log_error "Missing required dependencies: ${missing_deps[*]}"
        log_info "Please install the missing dependencies and try again."
        exit 1
    fi
    
    log_success "All dependencies found"
}

# Setup virtual environment
setup_venv() {
    if [ "$USE_VENV" = true ]; then
        log_info "Setting up Python virtual environment..."
        
        if [ ! -d "venv" ]; then
            python3 -m venv venv || {
                log_error "Failed to create virtual environment"
                exit 1
            }
        fi
        
        source venv/bin/activate || {
            log_error "Failed to activate virtual environment"
            exit 1
        }
        
        log_success "Virtual environment activated"
    else
        log_warning "Skipping virtual environment setup"
    fi
}

# Clean build artifacts
clean_build() {
    if [ "$CLEAN_BUILD" = true ]; then
        log_info "Cleaning existing build artifacts..."
        rm -rf build/
        rm -rf venv/
        log_success "Build artifacts cleaned"
    fi
}

# Clone or update grammar repositories
setup_grammars() {
    log_info "Setting up grammar repositories..."
    
    # Java grammar
    if [ -d "tree-sitter-java" ]; then
        if [ "$UPDATE_GRAMMARS" = true ]; then
            log_info "Updating Java grammar..."
            cd tree-sitter-java
            git pull origin master || {
                log_warning "Failed to update Java grammar, using existing version"
            }
            cd ..
        else
            log_info "Java grammar already exists, skipping clone"
        fi
    else
        log_info "Cloning Java grammar..."
        git clone https://github.com/tree-sitter/tree-sitter-java.git || {
            log_error "Failed to clone Java grammar"
            exit 1
        }
    fi
    
    # Kotlin grammar
    if [ -d "tree-sitter-kotlin" ]; then
        if [ "$UPDATE_GRAMMARS" = true ]; then
            log_info "Updating Kotlin grammar..."
            cd tree-sitter-kotlin
            git pull origin master || {
                log_warning "Failed to update Kotlin grammar, using existing version"
            }
            cd ..
        else
            log_info "Kotlin grammar already exists, skipping clone"
        fi
    else
        log_info "Cloning Kotlin grammar..."
        git clone https://github.com/fwcd/tree-sitter-kotlin.git || {
            log_error "Failed to clone Kotlin grammar"
            exit 1
        }
    fi
    
    log_success "Grammar repositories ready"
}

# Build language libraries
build_libraries() {
    log_info "Building language libraries..."
    
    # Install specific version of tree-sitter that supports build_library
    log_info "Installing compatible tree-sitter version..."
    pip install "tree-sitter==0.20.4" || {
        log_error "Failed to install tree-sitter Python package"
        exit 1
    }
    
    # Build Java language library
    log_info "Building Java language library..."
    python3 -c "
from tree_sitter import Language
import sys

try:
    Language.build_library(
        'java-language.so',
        ['tree-sitter-java']
    )
    print('Java language library built successfully')
except Exception as e:
    print(f'Error building Java library: {e}')
    sys.exit(1)
" || {
        log_error "Failed to build Java language library"
        exit 1
    }
    
    # Build Kotlin language library
    log_info "Building Kotlin language library..."
    python3 -c "
from tree_sitter import Language
import sys

try:
    Language.build_library(
        'kotlin-language.so', 
        ['tree-sitter-kotlin']
    )
    print('Kotlin language library built successfully')
except Exception as e:
    print(f'Error building Kotlin library: {e}')
    sys.exit(1)
" || {
        log_error "Failed to build Kotlin language library"
        exit 1
    }
    
    log_success "Language libraries built successfully"
}

# Test parsers
test_parsers() {
    log_info "Testing parsers..."
    
    # Test Java parser
    log_info "Testing Java parser..."
    python3 -c "
from tree_sitter import Language, Parser
import sys
import os

try:
    # Load Java language with correct path
    java_language = Language('./java-language.so', 'java')
    parser = Parser()
    parser.set_language(java_language)
    
    # Test parse
    code = '''
public class Test {
    public void testMethod() {
        System.out.println(\"Hello World\");
    }
    
    private int calculateSum(int a, int b) {
        return a + b;
    }
}
    '''
    
    tree = parser.parse(code.encode())
    root = tree.root_node
    
    if root.type == 'program':
        print(f'Java parser working correctly: {root.type}')
        print(f'Children count: {len(root.children)}')
    else:
        raise Exception(f'Unexpected root node type: {root.type}')
        
except Exception as e:
    print(f'Java parser test failed: {e}')
    sys.exit(1)
" || {
        log_error "Java parser test failed"
        exit 1
    }
    
    # Test Kotlin parser
    log_info "Testing Kotlin parser..."
    python3 -c "
from tree_sitter import Language, Parser
import sys

try:
    # Load Kotlin language with correct path
    kotlin_language = Language('./kotlin-language.so', 'kotlin')
    parser = Parser()
    parser.set_language(kotlin_language)
    
    # Test parse
    code = '''
class TestClass {
    fun testFunction(): String {
        return \"Hello Kotlin\"
    }
    
    private fun calculateSum(a: Int, b: Int): Int {
        return a + b
    }
}
    '''
    
    tree = parser.parse(code.encode())
    root = tree.root_node
    
    if root.type == 'source_file':
        print(f'Kotlin parser working correctly: {root.type}')
        print(f'Children count: {len(root.children)}')
    else:
        raise Exception(f'Unexpected root node type: {root.type}')
        
except Exception as e:
    print(f'Kotlin parser test failed: {e}')
    sys.exit(1)
" || {
        log_error "Kotlin parser test failed"
        exit 1
    }
    
    log_success "All parser tests passed"
}

# Create usage example
create_usage_example() {
    log_info "Creating usage example..."
    
    cat > example_usage.py << 'EOF'
#!/usr/bin/env python3
"""
Example usage of tree-sitter for Kotlin/Java AST parsing
"""

from tree_sitter import Language, Parser
import os

def demo_java_parsing():
    """Demonstrate Java AST parsing"""
    print("=== Java AST Parsing Demo ===")
    
    # Load Java language
    java_language = Language('./build/java-language.so', 'java')
    parser = Parser()
    parser.set_language(java_language)
    
    # Sample Java code
    java_code = '''
public class Calculator {
    public int add(int a, int b) {
        return a + b;
    }
    
    public double multiply(double x, double y) {
        return x * y;
    }
}
    '''
    
    # Parse the code
    tree = parser.parse(java_code.encode())
    
    # Walk the AST
    def walk_tree(node, depth=0):
        indent = "  " * depth
        print(f"{indent}{node.type}: {repr(java_code[node.start_byte:node.end_byte])}")
        for child in node.children:
            walk_tree(child, depth + 1)
    
    walk_tree(tree.root_node)

def demo_kotlin_parsing():
    """Demonstrate Kotlin AST parsing"""
    print("\n=== Kotlin AST Parsing Demo ===")
    
    # Load Kotlin language
    kotlin_language = Language('./build/kotlin-language.so', 'kotlin')
    parser = Parser()
    parser.set_language(kotlin_language)
    
    # Sample Kotlin code
    kotlin_code = '''
class Calculator {
    fun add(a: Int, b: Int): Int {
        return a + b
    }
    
    fun multiply(x: Double, y: Double): Double {
        return x * y
    }
}
    '''
    
    # Parse the code
    tree = parser.parse(kotlin_code.encode())
    
    # Extract function definitions
    def find_functions(node):
        functions = []
        if node.type == 'function_declaration':
            functions.append(node)
        for child in node.children:
            functions.extend(find_functions(child))
        return functions
    
    functions = find_functions(tree.root_node)
    print(f"Found {len(functions)} function(s):")
    
    for func in functions:
        func_text = kotlin_code[func.start_byte:func.end_byte]
        print(f"  - {func_text.split('{')[0].strip()}")

if __name__ == "__main__":
    if os.path.exists('./build/java-language.so') and os.path.exists('./build/kotlin-language.so'):
        demo_java_parsing()
        demo_kotlin_parsing()
    else:
        print("Language libraries not found. Please run setup_treesitter.sh first.")
EOF
    
    chmod +x example_usage.py
    log_success "Usage example created: example_usage.py"
}

# Main execution
main() {
    echo -e "${BLUE}🚀 Setting up Tree-sitter for Kotlin/Java AST parsing...${NC}"
    echo ""
    
    check_dependencies
    clean_build
    
    # Create build directory
    mkdir -p build
    cd build
    
    setup_venv
    setup_grammars
    build_libraries
    test_parsers
    
    cd ..
    create_usage_example
    
    echo ""
    echo -e "${GREEN}🎉 Tree-sitter setup complete!${NC}"
    echo ""
    echo -e "${BLUE}📁 Language libraries created in:${NC}"
    echo "   - build/java-language.so"
    echo "   - build/kotlin-language.so"
    echo ""
    echo -e "${BLUE}💡 Usage examples:${NC}"
    echo "   - Run demo: python3 example_usage.py"
    echo "   - Import in code: from tree_sitter import Language, Parser"
    echo ""
    echo -e "${BLUE}🔧 Virtual environment:${NC}"
    if [ "$USE_VENV" = true ]; then
        echo "   - Activate: source $venv_path/bin/activate"
        echo "   - Deactivate: deactivate"
    else
        echo "   - No virtual environment created (--no-venv used)"
    fi
}

# Run main function
main "$@"