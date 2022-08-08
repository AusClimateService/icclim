from __future__ import annotations

import numpy as np
import pandas as pd
import xarray
import xarray as xr

from icclim.models.constants import UNITS_ATTRIBUTE_KEY
from icclim.models.frequency import FrequencyRegistry
from icclim.models.index_config import ClimateVariable
from icclim.models.user_index_config import UserIndexConfig

VALUE_COUNT = 365 * 5 + 1  # 5 years of data (with 1 leap year)
COORDS = dict(
    lat=[42],
    lon=[42],
    time=pd.date_range("2042-01-01", periods=VALUE_COUNT, freq="D"),
)
K2C = 273.15

CF_TIME_RANGE = xr.cftime_range("2042-01-01", periods=VALUE_COUNT, freq="D")


def stub_user_index(cf_vars: list[ClimateVariable]):
    return UserIndexConfig(
        index_name="Yolo",
        calc_operation="noop",
        freq=FrequencyRegistry.MONTH,
        climate_variables=cf_vars,
    )


def stub_tas(tas_value: float = 1.0, use_dask=False, use_cftime=False):
    da = xarray.DataArray(
        data=(np.full(VALUE_COUNT, tas_value).reshape((VALUE_COUNT, 1, 1))),
        dims=["time", "lat", "lon"],
        coords=COORDS,
        attrs={UNITS_ATTRIBUTE_KEY: "K"},
    )
    if use_cftime:
        da["time"] = CF_TIME_RANGE
    if use_dask:
        da.chunk()
    return da


def stub_pr(value: float, use_dask=False):
    da = xarray.DataArray(
        data=np.full(VALUE_COUNT, value).reshape((VALUE_COUNT, 1, 1)),
        coords=COORDS,
        dims=["time", "lat", "lon"],
        name="pr",
        attrs={UNITS_ATTRIBUTE_KEY: "kg m-2 d-1"},
    )
    if use_dask:
        da.chunk()
    return da
