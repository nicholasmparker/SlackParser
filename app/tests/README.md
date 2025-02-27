# SlackParser Tests
# SlackParser Testing Guide

This document outlines the testing approach, best practices, and guidelines for the SlackParser application.

## Testing Philosophy

Our testing approach follows these key principles:

1. **Test Real Code**: Tests should verify actual functionality, not implementation details.
2. **Isolation**: Tests should be independent and not affect each other.
3. **Comprehensive Coverage**: Tests should cover happy paths, edge cases, and error scenarios.
4. **Maintainability**: Tests should be easy to understand and maintain.
5. **Speed**: Tests should run quickly to encourage frequent execution.

## Test Structure

The test suite is organized into three levels:

### 1. Unit Tests

Unit tests verify individual components in isolation, typically mocking external dependencies.

Examples:
- `test_parser.py`: Tests the Slack message parser functions
- `app/importer/test_parser.py`: Tests specific parser functionality

### 2. Integration Tests

Integration tests verify that components work together correctly.

Examples:
- `test_services.py`: Tests service layer components with real database connections
- `app/importer/test_importer.py`: Tests the importer with real file processing

### 3. End-to-End Tests

End-to-end tests verify complete user workflows from start to finish.

Examples:
- `test_end_to_end.py`: Tests the full pipeline from upload to search

## Running Tests

Tests are run in Docker to ensure a consistent environment. Use the `run_tests_in_docker.sh` script:

```bash
# Run all tests
./app/tests/run_tests_in_docker.sh

# Run a specific test module
./app/tests/run_tests_in_docker.sh --module test_parser

# Run a specific test function
./app/tests/run_tests_in_docker.sh --function test_parse_channel_metadata

# Run tests with coverage report
./app/tests/run_tests_in_docker.sh --coverage

# Run tests with a specific marker
./app/tests/run_tests_in_docker.sh --marker asyncio
```

## Test Fixtures

Common test fixtures are defined in `conftest.py`. These include:

- Database setup and teardown
- Test data generation
- Mock services
- Directory setup

Use these fixtures to maintain consistency across tests and avoid duplication.

## Best Practices

1. **Use Descriptive Test Names**: Test names should clearly describe what is being tested.
2. **One Assertion Per Test**: Each test should verify one specific behavior.
3. **Use Fixtures**: Leverage pytest fixtures for setup and teardown.
4. **Mock External Dependencies**: Use mocks for external services to ensure test isolation.
5. **Test Edge Cases**: Include tests for boundary conditions and error scenarios.
6. **Use Markers**: Use pytest markers to categorize tests (e.g., `@pytest.mark.asyncio`).
7. **Clean Up Resources**: Ensure tests clean up any resources they create.
8. **Avoid Test Interdependence**: Tests should not depend on the state from other tests.

## Adding New Tests

When adding new functionality, follow this process:

1. Write unit tests for individual components
2. Write integration tests for component interactions
3. Update or add end-to-end tests for complete workflows
4. Run the full test suite to ensure no regressions

This directory contains tests for the SlackParser application. The tests are designed to verify the functionality of all key components of the application.

## Test Structure

The tests are organized into several files:

- `test_services.py`: Tests for individual services (Upload, Extraction, Import, Search)
- `test_end_to_end.py`: End-to-end tests for the full pipeline
- `test_pipeline.py`: Tests for the import pipeline stages
- `test_import.py`: Tests for the import functionality
- `test_embeddings.py`: Tests for the embeddings service
- `test_parser.py`: Tests for the Slack message parser

## Running Tests

You can run the tests using the `run_tests.py` script in the root directory:

```bash
# Run all tests
python app/run_tests.py

# Run a specific test module
python app/run_tests.py --module test_services

# Run a specific test function
python app/run_tests.py --function test_upload_service

# Run with verbose output
python app/run_tests.py --verbose

# Generate coverage report
python app/run_tests.py --coverage
```

## Test Environment

The tests use a test MongoDB database (`test_db`) and temporary directories for uploads and extracts. The test environment is isolated from the production environment to avoid any interference.

## Key Functions Tested

The tests cover all key functions of the SlackParser application:

1. **Upload**: Testing file uploads, validation, and storage
2. **Extract**: Testing ZIP file extraction and progress tracking
3. **Import**: Testing Slack export file parsing and database storage
4. **Embed**: Testing semantic search embeddings
5. **View**: Testing conversation and message retrieval
6. **Search**: Testing text search and semantic search

## Test Data

The tests use synthetic Slack export data that follows the format specified in the application. The test data includes:

- Channel files with metadata and messages
- DM files with metadata and messages
- Various message types (regular, join, etc.)

## Error Handling

The tests also verify error handling in the application, including:

- Invalid ZIP files
- Missing files
- Database errors

## Mocking

Some tests use mocking to isolate components and test them independently. For example, the embeddings service is mocked in some tests to avoid the need for a running Chroma DB instance.
