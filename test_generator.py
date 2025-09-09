#!/usr/bin/env python3
import sys
import re
import random
import argparse
from pathlib import Path

HUNK_HEADER = re.compile(r'^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@(.*)$')
FILE_HEADER = re.compile(r'^(---|\+\+\+) ([^\t\n]+)(?:\t(.+))?')

class PatchCorruptor:
    """Generate test cases by corrupting valid patches in various ways."""
    
    def __init__(self, patch_lines):
        self.original_lines = patch_lines.copy()
        self.test_cases = []
    
    def corrupt_file_headers(self):
        """Create test cases with corrupted file headers."""
        lines = self.original_lines.copy()
        test_cases = []
        
        # Missing --- header
        case1 = []
        skip_next_minus = True
        for line in lines:
            if skip_next_minus and line.startswith('---'):
                skip_next_minus = False
                continue
            case1.append(line)
        test_cases.append(('missing_minus_header', case1))
        
        # Missing +++ header
        case2 = []
        skip_next_plus = True
        for line in lines:
            if skip_next_plus and line.startswith('+++'):
                skip_next_plus = False
                continue
            case2.append(line)
        test_cases.append(('missing_plus_header', case2))
        
        # Swapped headers
        case3 = []
        i = 0
        while i < len(lines):
            if i + 1 < len(lines) and lines[i].startswith('---') and lines[i+1].startswith('+++'):
                case3.append(lines[i+1])  # Swap
                case3.append(lines[i])
                i += 2
            else:
                case3.append(lines[i])
                i += 1
        test_cases.append(('swapped_headers', case3))
        
        # Malformed paths
        case4 = []
        for line in lines:
            if line.startswith('---'):
                case4.append('--- this/is/wrong/path.txt\n')
            elif line.startswith('+++'):
                case4.append('+++ another/wrong/path.txt\n')
            else:
                case4.append(line)
        test_cases.append(('wrong_paths', case4))
        
        return test_cases
    
    def corrupt_hunk_headers(self):
        """Create test cases with corrupted hunk headers."""
        test_cases = []
        
        # Wrong line numbers
        case1 = []
        for line in self.original_lines:
            match = HUNK_HEADER.match(line)
            if match:
                old_start = random.randint(1, 100)
                old_count = match.group(2) or '1'
                new_start = random.randint(1, 100)
                new_count = match.group(4) or '1'
                context = match.group(5) or ''
                case1.append(f'@@ -{old_start},{old_count} +{new_start},{new_count} @@{context}\n')
            else:
                case1.append(line)
        test_cases.append(('wrong_line_numbers', case1))
        
        # Wrong line counts
        case2 = []
        for line in self.original_lines:
            match = HUNK_HEADER.match(line)
            if match:
                old_start = match.group(1)
                old_count = str(random.randint(1, 20))
                new_start = match.group(3)
                new_count = str(random.randint(1, 20))
                context = match.group(5) or ''
                case2.append(f'@@ -{old_start},{old_count} +{new_start},{new_count} @@{context}\n')
            else:
                case2.append(line)
        test_cases.append(('wrong_line_counts', case2))
        
        # Missing hunk headers
        case3 = []
        skip_next_hunk = True
        for line in self.original_lines:
            if skip_next_hunk and HUNK_HEADER.match(line):
                skip_next_hunk = False
                continue
            case3.append(line)
        test_cases.append(('missing_hunk_header', case3))
        
        # Malformed hunk header format
        case4 = []
        for line in self.original_lines:
            if HUNK_HEADER.match(line):
                case4.append('@@ malformed hunk header @@\n')
            else:
                case4.append(line)
        test_cases.append(('malformed_hunk_header', case4))
        
        return test_cases
    
    def corrupt_content(self):
        """Create test cases with corrupted content."""
        test_cases = []
        
        # Extra whitespace
        case1 = []
        for line in self.original_lines:
            if line.startswith(('+', '-', ' ')) and not line.startswith(('+++', '---')):
                case1.append(line.rstrip() + '    \n')  # Add trailing whitespace
            else:
                case1.append(line)
        test_cases.append(('extra_whitespace', case1))
        
        # Mixed line endings
        case2 = []
        for i, line in enumerate(self.original_lines):
            if i % 2 == 0:
                case2.append(line.rstrip('\r\n') + '\r\n')
            else:
                case2.append(line.rstrip('\r\n') + '\n')
        test_cases.append(('mixed_line_endings', case2))
        
        # Missing context lines
        case3 = []
        skip_context = 0
        for line in self.original_lines:
            if line.startswith(' ') and skip_context < 2:
                skip_context += 1
                continue
            case3.append(line)
        test_cases.append(('missing_context', case3))
        
        # Duplicated lines
        case4 = []
        for line in self.original_lines:
            case4.append(line)
            if line.startswith('+') and random.random() < 0.3:
                case4.append(line)  # Duplicate some additions
        test_cases.append(('duplicated_lines', case4))
        
        # Wrong prefixes
        case5 = []
        for line in self.original_lines:
            if line.startswith(' ') and random.random() < 0.1:
                case5.append('?' + line[1:])  # Wrong prefix
            else:
                case5.append(line)
        test_cases.append(('wrong_prefixes', case5))
        
        return test_cases
    
    def generate_all_test_cases(self):
        """Generate all types of test cases."""
        all_cases = []
        all_cases.extend(self.corrupt_file_headers())
        all_cases.extend(self.corrupt_hunk_headers())
        all_cases.extend(self.corrupt_content())
        return all_cases
    
    def generate_combined_corruption(self):
        """Generate a test case with multiple types of corruption."""
        lines = self.original_lines.copy()
        
        # Apply multiple corruptions
        corruptions_applied = []
        
        # Randomly corrupt some hunk headers
        for i, line in enumerate(lines):
            if HUNK_HEADER.match(line) and random.random() < 0.5:
                old_start = random.randint(1, 50)
                lines[i] = re.sub(r'-\d+', f'-{old_start}', line)
                corruptions_applied.append('wrong_line_number')
                break
        
        # Add some whitespace issues
        for i, line in enumerate(lines):
            if line.startswith(('+', '-', ' ')) and random.random() < 0.3:
                lines[i] = line.rstrip() + '   \n'
                if 'extra_whitespace' not in corruptions_applied:
                    corruptions_applied.append('extra_whitespace')
        
        # Mix line endings
        for i in range(0, len(lines), 3):
            if i < len(lines):
                lines[i] = lines[i].rstrip('\r\n') + '\r\n'
        corruptions_applied.append('mixed_endings')
        
        name = 'combined_' + '_'.join(corruptions_applied)[:50]
        return (name, lines)

def main():
    parser = argparse.ArgumentParser(description='Generate test cases from valid git diff')
    parser.add_argument('input_patch', help='Valid git diff/patch file')
    parser.add_argument('output_dir', help='Directory to write test cases')
    parser.add_argument('--types', nargs='+', 
                       choices=['headers', 'hunks', 'content', 'combined', 'all'],
                       default=['all'],
                       help='Types of corruptions to generate')
    parser.add_argument('--count', type=int, default=1,
                       help='Number of combined corruption variants to generate')
    
    args = parser.parse_args()
    
    # Read input patch
    with open(args.input_patch, 'r', encoding='utf-8') as f:
        patch_lines = f.readlines()
    
    # Create output directory
    output_path = Path(args.output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    
    corruptor = PatchCorruptor(patch_lines)
    test_cases = []
    
    # Generate requested test cases
    if 'all' in args.types:
        test_cases = corruptor.generate_all_test_cases()
    else:
        if 'headers' in args.types:
            test_cases.extend(corruptor.corrupt_file_headers())
        if 'hunks' in args.types:
            test_cases.extend(corruptor.corrupt_hunk_headers())
        if 'content' in args.types:
            test_cases.extend(corruptor.corrupt_content())
    
    if 'combined' in args.types or 'all' in args.types:
        for i in range(args.count):
            name, lines = corruptor.generate_combined_corruption()
            if args.count > 1:
                name = f"{name}_{i+1}"
            test_cases.append((name, lines))
    
    # Write test cases
    print(f"Generating {len(test_cases)} test cases in {output_path}")
    for name, lines in test_cases:
        output_file = output_path / f"test_{name}.patch"
        with open(output_file, 'w', encoding='utf-8') as f:
            f.writelines(lines)
        print(f"  Created: {output_file.name}")
    
    # Create a description file
    desc_file = output_path / "test_descriptions.txt"
    with open(desc_file, 'w') as f:
        f.write("Test Cases Generated\n")
        f.write("=" * 50 + "\n\n")
        for name, _ in test_cases:
            f.write(f"test_{name}.patch:\n")
            f.write(f"  Type: {name.replace('_', ' ').title()}\n")
            f.write("\n")
    
    print(f"\nTest descriptions written to: {desc_file.name}")
    print(f"Total test cases generated: {len(test_cases)}")

if __name__ == "__main__":
    main()
