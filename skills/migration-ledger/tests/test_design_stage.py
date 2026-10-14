"""The test design a leaf carries is the Spec-Designer's own: an upstream test plan submitted with the plan. These
helpers give a fixture plan that test design."""
import sys
import unittest

import test_iterative_spec


def prepare_design(f, plan, mid='M001'):
    """Give a fixture plan the upstream test plan the Spec-Designer submits with it."""
    plan['module_id'] = mid
    test_iterative_spec.direct_plan(f, plan)
    return plan


if __name__ == '__main__':
    unittest.main()
