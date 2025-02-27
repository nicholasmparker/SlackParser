#!/usr/bin/env python
"""
Run tests for the SlackParser application.
This script runs all tests or specific test modules based on command line arguments.
"""

import os
import sys
import argparse
import pytest

def main():
    """Run tests for the SlackParser application."""
    parser = argparse.ArgumentParser(description="Run tests for the SlackParser application")
    parser.add_argument(
        "--module", "-m", 
        help="Specific test module to run (e.g., 'test_services' or 'test_pipeline')"
    )
    parser.add_argument(
        "--function", "-f", 
        help="Specific test function to run (e.g., 'test_upload_service')"
    )
    parser.add_argument(
        "--verbose", "-v", 
        action="store_true", 
        help="Enable verbose output"
    )
    parser.add_argument(
        "--coverage", "-c", 
        action="store_true", 
        help="Generate coverage report"
    )
    
    args = parser.parse_args()
    
    # Set environment variables for testing
    os.environ["MONGO_DB"] = "test_db"
    
    # Build pytest arguments
    pytest_args = []
    
    if args.verbose:
        pytest_args.append("-v")
    
    if args.coverage:
        pytest_args.extend(["--cov=app", "--cov-report=term", "--cov-report=html"])
    
    # Determine which tests to run
    if args.module:
        if args.function:
            pytest_args.append(f"app/tests/{args.module}.py::{args.function}")
        else:
            pytest_args.append(f"app/tests/{args.module}.py")
    elif args.function:
        # Search for the function in all test modules
        pytest_args.append(f"app/tests/::/{args.function}")
    else:
        # Run all tests
        pytest_args.append("app/tests/")
    
    # Run pytest
    return pytest.main(pytest_args)

if __name__ == "__main__":
    sys.exit(main())
