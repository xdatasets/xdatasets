from typing import Sequence, Tuple, Union, Dict, List

from clisops.core.subset import subset_shape, subset_time, create_mask, shape_bbox_indexer
from clisops.core.average import average_shape
import intake
import s3fs
import geopandas as gpd
import hvplot.xarray
import hvplot.pandas
import xarray as xr
import numpy as np
import warnings
from tqdm import tqdm
import pandas as pd
import pytz


URL_PATH = 'https://raw.githubusercontent.com/hydrocloudservices/catalogs/main/catalogs/main.yaml'

__all__ = ["Dataset"]


def shift_tz(ds, timezone):
    ds_copy = ds.copy()

    time = ds_copy['time'].to_index()

    time_utc = time.tz_localize(pytz.UTC)
    local_tz = pytz.timezone(timezone)
    time_local = time_utc.tz_convert(local_tz).tz_localize(None)

    # create a new dataset that replaces/updates the UTC time in the original dataset with the local time from the newly created dataset (in pandas)
    ds_copy = ds_copy.update({'time': time_local})
    ds_copy.attrs['timezone'] = timezone

    return ds_copy


class Dataset:
    """"This is the base class for the datasets extension for xarray"""
    def __init__(self,
                 variables: Union[str, Dict[str, Union[str, List[str]]]],
                 space: Dict[str, Union[str, List[str]]],
                 time=None,
                 url_path: str = URL_PATH):

        self.catalog = intake.open_catalog(url_path)
        self.variables = variables
        self.space = space
        self.time = time
        
        self.load_dataset(variables=self.variables,
                          space=self.space,
                          time=self.time)

    def load_dataset(self,
                     variables: Union[str, Dict[str, Union[str, List[str]]]],
                     space: Dict[str, Union[str, List[str]]],
                     time=None):

        # Get all datasets in query
        datasets_name = list(variables.keys())

        clip_available_methods = ['bbox', 'point', 'polygon']
        if space['clip'] not in clip_available_methods:
            raise ValueError(f"Clip argument '{space['clip']}' is not one of {clip_available_methods}")

        # Load data for each dataset
        for dataset_name in datasets_name:
            variables_name = variables[dataset_name]

            # get spatial aggregation

            #

            data = self._load_data_from_one_dataset(dataset_name=dataset_name,
                                                    variables=variables_name,
                                                    space=space,
                                                    time=time)
            return self

    def _load_data_from_one_dataset(self,
                                    dataset_name,
                                    variables,
                                    space,
                                    time):

        # Fetch field from dataset name
        field = 'atmosphere'  # temporary

        ds = self.catalog[field][dataset_name].to_dask()

        #
        try:
            ds = ds[variables]
        except:
            pass

        if time['start'] and time['end']:
            try:
                ds = subset_time(ds, start_date=time['start'], end_date=time['end'])
            except:
                pass
            # replace by error

        if time['timezone']:
            try:
                ds = shift_tz(ds, time['timezone'])
            except:
                pass
          # replace by error
        

        if space['clip'] == 'polygon':
            indexer = shape_bbox_indexer(ds, space['geometry'])
            ds = ds.isel(indexer)
            if space['aggregation'] is True:
                arrays = []
                for idx, _ in tqdm(space['geometry'].iterrows()):
                    indexer = shape_bbox_indexer(ds, space['geometry'].iloc[[idx]])
                    da = ds.isel(indexer)
                    pr = da.chunk({'latitude':-1, 'longitude':-1})

                    # Average data array over shape
                    ds_avg = average_shape(pr, shape=space['geometry'].iloc[[idx]])
                    arrays.append(ds_avg)
                ds = xr.concat(arrays, dim='geom')

                if space['unique_id']:
                    try:
                        ds = ds.swap_dims({"geom": space["unique_id"]})
                    except:
                        pass
                # replace by error
        
        data = xr.Dataset(attrs=ds.attrs)

        if time['timestep']:
            pbar = tqdm(variables)
            for var in pbar:
                pbar.set_description("Processing %s" % var)
                try:
                    # Verify if requested timestep is higher or lower or equal to dataset's native timestep

                    # if requested timestep is higher 
                    if 'aggregation' in time:
                        operation = time['aggregation'][var] if var in time['aggregation'].keys() else None
                        operation = operation if isinstance(operation, list)  else [operation]
                        for oper in operation:
                            var_name = f"{var}_{oper.__name__}"
                            data[var_name] = ds[var].resample(time=time['timestep']).reduce(oper, dim='time')
                    # if requested timestep is lower
                    # bfill the timestep and add a warning

                    # if requested timestep is equal : do nothing


                except:
                    pass



        #     data = subset_shape(ds, shape=space['geometry'])

        # # Load data in memory
        # data = data.copy()
        # data = data.chunk(dict(latitude=-1, longitude=-1)).load()

        # for var in tqdm(variables):
        #     if 'aggregation' in space:
        #         operation = space['aggregation'][var] if var in space['aggregation'].keys() else None

        #         if operation:
        #             with warnings.catch_warnings():
        #                 warnings.simplefilter("ignore", category=RuntimeWarning)
        #                 data[var] = data[var].reduce(operation, dim=['latitude', 'longitude'])

        self.data = data.squeeze().load()
        return self

    def plot(self,
             variables=None):

        variables = ['t2m', 'tp']

        return self.data[variables].hvplot(x='time', grid=True, subplots=True, shared_axes=False, by='geom', legend=True).cols(1)

