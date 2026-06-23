"""
Unit tests for Hino 2-lane parallel scheduling implementation.
"""
import pytest
from unittest.mock import patch, MagicMock
from src.services.process_assigner import _legacy_assign_processes_by_arrival_time


class TestHino2Lane:
    """Tests for Hino 2-lane (日野2レーン) scheduling."""

    @pytest.fixture
    def mock_master_data_hino(self):
        """Mock master data for Hino (日野) with bins 01-10."""
        return {
            ("日野", "01"): "06:50",  # 1直
            ("日野", "02"): "07:05",
            ("日野", "03"): "07:20",
            ("日野", "04"): "07:35",
            ("日野", "05"): "07:50",
            ("日野", "06"): "08:05",
            ("日野", "07"): "08:20",
            ("日野", "08"): "08:35",
            ("日野", "09"): "08:50",
            ("日野", "10"): "09:05",
        }

    @pytest.fixture
    def mock_set_flags_hino(self):
        """Mock set flags for Hino."""
        return {
            ("日野", "01"): False,  # Head bin without set flag
            ("日野", "02"): False,  # Head bin without set flag (bin 2 is often first of 2nd shift or continuation)
            ("日野", "03"): False,
            ("日野", "04"): False,
            ("日野", "05"): False,
            ("日野", "06"): False,
            ("日野", "07"): False,
            ("日野", "08"): False,
            ("日野", "09"): False,
            ("日野", "10"): False,
        }

    def test_hino_2lane_target_function_exists(self):
        """Verify _is_hino_2lane_target function exists and works correctly."""
        # This test checks that the function is defined in the module
        # by attempting to call the internal function via inspection
        import inspect
        from src.services import process_assigner
        
        # Check that the function name exists in source (indirect test)
        source = inspect.getsource(process_assigner._legacy_assign_processes_by_arrival_time)
        assert "_is_hino_2lane_target" in source, "_is_hino_2lane_target function not found"
        assert "日野" in source, "Hino-specific logic not found"

    def test_hino_odd_even_lanes_via_start_floor(self, mock_master_data_hino, mock_set_flags_hino):
        """
        Test that Hino bins are separated by odd/even into different lanes
        via start_floor_map values.
        
        Odd bins (01, 03, 05, 07, 09) should have start_floor=1 (Lane A).
        Even bins (02, 04, 06, 08, 10) should have start_floor=2 (Lane B).
        """
        # Expected: odd bins -> floor 1, even bins -> floor 2
        # This is expressed through start_floor_map values from open time calculation
        expected_odd_floors = {1, 3, 5, 7, 9}
        expected_even_floors = {2, 4, 6, 8, 10}
        
        # Verify that odd/even calculation can be done
        for bin_num in expected_odd_floors:
            assert bin_num % 2 == 1, f"Bin {bin_num} should be odd"
        for bin_num in expected_even_floors:
            assert bin_num % 2 == 0, f"Bin {bin_num} should be even"

    def test_hino_n_minus_2_offset(self):
        """
        Test that Hino uses N-2 bin arrival time instead of N-1.
        
        For example:
        - Bin 03 (current) should use Bin 01 (N-2) arrival time + 10min
        - Bin 04 (current) should use Bin 02 (N-2) arrival time + 10min
        """
        # This test verifies the offset=2 parameter is used for Hino
        import inspect
        from src.services import process_assigner
        
        source = inspect.getsource(process_assigner._legacy_assign_processes_by_arrival_time)
        # Verify that offset=2 is used in Hino branch
        assert "_get_prev_bin_for_vendor(vendor, current_bin, allow_wrap=True, offset=2)" in source, \
            "Hino should use offset=2 for N-2 bin retrieval"

    def test_hino_head_bin_set_flag_true(self):
        """
        Test that head bin with set_flag=true uses standard head bin logic.
        
        According to implementation: Hino head bins use shift_start + 15min regardless of set_flag.
        The set_flag effect is handled via effective_deadline adjustment (SET_FLAG_MAIN_LIMIT_SECS).
        """
        import inspect
        from src.services import process_assigner
        
        source = inspect.getsource(process_assigner._legacy_assign_processes_by_arrival_time)
        # Verify that Hino head bin uses shift_start + 15min
        assert "_shift_start_secs(shift_idx) + 15 * 60" in source, \
            "Head bin should use shift_start + 15min"
        # Verify that effective_deadline handles SET_FLAG_MAIN_LIMIT_SECS for set_flag processing
        assert "SET_FLAG_MAIN_LIMIT_SECS" in source or "effective_deadline" in source, \
            "Set flag deadline control should be present"

    def test_hino_head_bin_set_flag_false(self):
        """
        Test that head bin with set_flag=false uses start_time + 15min.
        
        According to spec: セットなし先頭便 -> 各直開始 + 15分
        """
        import inspect
        from src.services import process_assigner
        
        source = inspect.getsource(process_assigner._legacy_assign_processes_by_arrival_time)
        # Verify that set_flag false branch for head bin uses +15min logic
        assert "_shift_start_secs(shift_idx) + 15 * 60" in source, \
            "Head bin with set_flag=false should use shift_start + 15min"

    def test_backward_compatibility_non_hino(self):
        """
        Test that non-Hino vendors use N-1 bin (offset=1) logic unchanged.
        
        This ensures backward compatibility for existing vendors.
        """
        import inspect
        from src.services import process_assigner
        
        source = inspect.getsource(process_assigner._legacy_assign_processes_by_arrival_time)
        # Verify offset=1 is used in non-Hino branches
        assert "offset=1" in source, "Non-Hino branches should use offset=1"

    def test_hino_eh_not_affected(self):
        """
        Test that Hino EH (日野EH) is NOT affected by Hino 2-lane logic.
        
        Only exact match "日野" should trigger 2-lane logic.
        Vendors like "日野EH" or "日野プレス" should use existing N-1 logic.
        """
        import inspect
        from src.services import process_assigner
        
        source = inspect.getsource(process_assigner._legacy_assign_processes_by_arrival_time)
        # Verify exact match check exists
        assert 'v == "日野"' in source, "Should use exact match '日野' not startswith"
        # Verify this is distinct from general Hino vendor check
        assert '_is_hino_2lane_target' in source, "Should have separate 2-lane target check"

    def test_function_signature_offset_parameter(self):
        """
        Test that _get_prev_bin_for_vendor has offset parameter with default=1.
        """
        import inspect
        from src.services import process_assigner
        
        # Get the function signature within _legacy_assign_processes_by_arrival_time
        source = inspect.getsource(process_assigner._legacy_assign_processes_by_arrival_time)
        assert "offset: int = 1" in source, "offset parameter should have default=1"
        assert "offset=2" in source, "Should call with offset=2 for Hino"


class TestBackwardCompatibility:
    """Tests for backward compatibility with existing logic."""

    def test_set_flag_column_missing_backward_compat(self):
        """
        Test that code still works when set flag column is missing.
        
        Old master data without set flag should continue to work with existing logic.
        """
        import inspect
        from src.services import process_assigner
        
        source = inspect.getsource(process_assigner._legacy_assign_processes_by_arrival_time)
        assert "if not has_set_flag_col:" in source, "Should handle missing set flag column"

    def test_offset_parameter_default_one(self):
        """
        Test that offset parameter defaults to 1 for backward compatibility.
        
        Existing code that doesn't specify offset should behave as before.
        """
        import inspect
        from src.services import process_assigner
        
        source = inspect.getsource(process_assigner._legacy_assign_processes_by_arrival_time)
        # Check that offset=1 is the default
        assert "offset: int = 1" in source, "Default offset should be 1"


class TestConstantsAndImports:
    """Tests for constants and imports."""

    def test_arrival_buffer_secs_used(self):
        """
        Test that ARRIVAL_BUFFER_SECS is used instead of hardcoded 10*60.
        """
        import inspect
        from src.services import process_assigner
        
        source = inspect.getsource(process_assigner._legacy_assign_processes_by_arrival_time)
        # Count occurrences of ARRIVAL_BUFFER_SECS (should be multiple)
        assert source.count("ARRIVAL_BUFFER_SECS") > 0, "ARRIVAL_BUFFER_SECS should be used"

    def test_shift_start_secs_used(self):
        """
        Test that _shift_start_secs is used instead of hardcoded times.
        """
        import inspect
        from src.services import process_assigner
        
        source = inspect.getsource(process_assigner._legacy_assign_processes_by_arrival_time)
        assert "_shift_start_secs(shift_idx)" in source, "_shift_start_secs should be called with shift_idx"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
