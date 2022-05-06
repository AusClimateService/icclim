from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import cftime
import numpy as np
import pandas as pd
import pytest
import xarray as xr

import icclim
from icclim.ecad.ecad_indices import EcadIndex
from icclim.models.constants import ICCLIM_VERSION
from icclim.models.frequency import Frequency
from icclim.models.index_group import IndexGroup


@patch("icclim.main.index")
@patch("icclim.icclim_logger.IcclimLogger")
def test_deprecated_indice(log_mock: MagicMock, index_mock: MagicMock):
    icclim.main.log = log_mock
    icclim.indice()
    log_mock.deprecation_warning.assert_called_once_with(
        old="icclim.indice", new="icclim.index"
    )
    index_mock.assert_called_once()


HEAT_INDICES = ["SU", "TR", "WSDI", "TG90p", "TN90p", "TX90p", "TXx", "TNx", "CSU"]


@pytest.mark.slow
class Test_Integration:
    """
    Simple integration test.
    We are not testing here the actual indices results, they are already tested in
    `test_ecad_indices.py` as well as in xclim directly.
    The goal it to make sure every the whole app can run smoothly

    These tests have side effect:
    - writing and removing of "out.nc" file

    """

    OUTPUT_FILE = "out.nc"
    TIME_RANGE = pd.date_range(start="2042-01-01", end="2045-12-31", freq="D")
    CF_TIME_RANGE = xr.cftime_range("2042-01-01", end="2045-12-31", freq="D")
    data = xr.DataArray(
        data=(np.full(len(TIME_RANGE), 20).reshape((len(TIME_RANGE), 1, 1))),
        dims=["time", "lat", "lon"],
        coords=dict(
            lat=[42],
            lon=[42],
            time=TIME_RANGE,
        ),
        attrs={"units": "degC"},
    )

    data_cf_time = xr.DataArray(
        data=(np.full(len(TIME_RANGE), 20).reshape((len(TIME_RANGE), 1, 1))),
        dims=["time", "lat", "lon"],
        coords=dict(
            lat=[42],
            lon=[42],
            time=CF_TIME_RANGE,
        ),
        attrs={"units": "degC"},
    )

    @pytest.fixture(autouse=True)
    def cleanup(self):
        # setup
        # ...
        yield
        # teardown
        try:
            os.remove(self.OUTPUT_FILE)
        except FileNotFoundError:
            pass

    def test_index_SU(self):
        res = icclim.index(
            indice_name="SU", in_files=self.data, out_file=self.OUTPUT_FILE
        )
        assert f"icclim version: {ICCLIM_VERSION}" in res.attrs["history"]
        np.testing.assert_array_equal(0, res.SU)

    def test_index_SU__monthy_sampled(self):
        res = icclim.index(
            indice_name="SU",
            in_files=self.data,
            out_file=self.OUTPUT_FILE,
            slice_mode=Frequency.MONTH,
        )
        np.testing.assert_array_equal(0, res.SU)
        np.testing.assert_array_equal(
            len(np.unique(self.TIME_RANGE.year)) * 12, len(res.time)
        )

    def test_index_SU__monthy_sampled_cf_time(self):
        res = icclim.index(
            indice_name="SU",
            in_files=self.data_cf_time,
            out_file=self.OUTPUT_FILE,
            slice_mode=Frequency.MONTH,
        )
        np.testing.assert_array_equal(0, res.SU)
        np.testing.assert_array_equal(
            len(np.unique(self.TIME_RANGE.year)) * 12, len(res.time)
        )
        assert res.time_bounds.sel(time=res.time[0])[0] == cftime.DatetimeGregorian(
            2042, 1, 1, 0, 0, 0, 0
        )
        assert res.time_bounds.sel(time=res.time[0])[1] == cftime.DatetimeGregorian(
            2042, 1, 31, 0, 0, 0, 0
        )

    def test_index_SU__DJF_cf_time(self):
        res = icclim.index(
            indice_name="SU",
            in_files=self.data_cf_time,
            out_file=self.OUTPUT_FILE,
            slice_mode=Frequency.DJF,
        )
        np.testing.assert_array_equal(res.SU.isel(time=0), np.NAN)
        np.testing.assert_array_equal(res.SU.isel(time=1), 0)
        # "+ 1" because DJF sampling create a december month with nans before first year
        np.testing.assert_array_equal(
            len(np.unique(self.TIME_RANGE.year)) + 1, len(res.time)
        )
        assert res.time_bounds.sel(time=res.time[0])[0] == cftime.DatetimeGregorian(
            2041, 12, 1, 0, 0, 0, 0
        )
        assert res.time_bounds.sel(time=res.time[0])[1] == cftime.DatetimeGregorian(
            2042, 2, 28, 0, 0, 0, 0
        )

    def test_indices_from_DataArray(self):
        res = icclim.indices(
            index_group=IndexGroup.HEAT, in_files=self.data, out_file=self.OUTPUT_FILE
        )
        for i in HEAT_INDICES:
            assert res[i] is not None

    def test_indices__snow_indices(self):
        ds = self.data.to_dataset(name="tas")
        ds["prec"] = self.data.copy(deep=True)
        ds["prec"].attrs["units"] = "cm"
        res = icclim.indices(
            index_group=IndexGroup.SNOW, in_files=ds, out_file=self.OUTPUT_FILE
        )
        for i in filter(lambda i: i.group == IndexGroup.SNOW, EcadIndex):
            assert res[i] is not None

    def test_indices_all_from_Dataset(self):
        ds = self.data.to_dataset(name="tas")
        ds["tasmax"] = self.data
        ds["tasmin"] = self.data
        ds["pr"] = self.data.copy(deep=True)
        ds["pr"].attrs["units"] = "kg m-2 d-1"
        ds["prec"] = self.data.copy(deep=True)
        ds["prec"].attrs["units"] = "cm"
        res = icclim.indices(
            index_group="all", in_files=ds, out_file=self.OUTPUT_FILE, ignore_error=True
        )
        for i in EcadIndex:
            assert res[i.short_name] is not None

    def test_indices_all_ignore_error(self):
        ds = self.data.to_dataset(name="tas")
        ds["tasmax"] = self.data
        ds["tasmin"] = self.data
        ds["pr"] = self.data.copy(deep=True)
        ds["pr"].attrs["units"] = "kg m-2 d-1"
        res: xr.Dataset = icclim.indices(
            index_group="all",
            in_files=ds,
            out_file=self.OUTPUT_FILE,
            ignore_error=True,
            slice_mode="DJF",
        ).compute()
        for i in EcadIndex:
            # No variable in input to compute snow indices
            if i.group == IndexGroup.SNOW:
                assert res.data_vars.get(i.short_name, None) is None
            else:
                # print("----------")
                # print(i.short_name)
                # print(res[i.short_name])
                assert res[i.short_name] is not None

    def test_indices_all_error(self):
        ds = self.data.to_dataset(name="tas")
        ds["tasmax"] = self.data
        ds["tasmin"] = self.data
        ds["pr"] = self.data.copy(deep=True)
        ds["pr"].attrs["units"] = "kg m-2 d-1"
        with pytest.raises(Exception):
            icclim.indices(
                index_group="all",
                in_files=ds,
                out_file=self.OUTPUT_FILE,
                ignore_error=False,
            )
