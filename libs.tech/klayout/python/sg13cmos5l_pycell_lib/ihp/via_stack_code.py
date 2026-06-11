########################################################################
#
# Copyright 2023 IHP PDK Authors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
########################################################################

## CUSTOM UPDATE SUMMARY:
## 1. Added new parameters to allow users to control the via array size based on either the number of rows/columns or the total width/height of the via array.
## 2. Added an option to add extra vias to fill the area under the bigger vias (like the TopVia1).
## 3. Updated the code to process the new parameters and draw the via array accordingly.
## 4. Updated the code to handle the new added layers (Activ/GatPoly) using the same metal process as the regular metals, and only add the contact layer if they are included in the stack.
## 5. Updated the code to ensure that the generated metal shapes respect the minimum width/height rules for TopMetal1 and the minimum metal area rule for all metals, to avoid DRC errors.

__version__ = '$Revision: #3 $'

from cni.dlo import *
from .geometry import *
from .thermal import *
from .utility_functions import *

import math

class via_stack(DloGen):

    @classmethod
    def defineParamSpecs(self, specs):
        # define parameters and default values
        techparams = specs.tech.getTechParams()
        
#ifdef KLAYOUT
#else
        CDFVersion = techparams['CDFVersion']
        specs('cdf_version', CDFVersion, 'CDF Version')
#endif

        # SG13CMOS5L: M1-M4-TM1 stack (Metal5 removed, TopMetal1 as top layer)
        ## UPDATE: ADD Activ/Gatpoly layers
        specs('b_layer', 'Metal1', 'Bottom layer', ChoiceConstraint(['Activ','GatPoly','Metal1', 'Metal2', 'Metal3', 'Metal4', 'TopMetal1']))
        specs('t_layer', 'Metal2', 'Top layer', ChoiceConstraint(['Metal1', 'Metal2', 'Metal3', 'Metal4', 'TopMetal1']))
        specs('vn_columns', 2, 'Via_n Columns')
        specs('vn_rows', 2, 'Via_n Rows')
        ## UPDATE: Option to fill the area under the bigger vias
        specs('extra_vias', 'no', 'Add extra vias', ChoiceConstraint(['yes', 'no']))
        ## UPDATE: Option to choose between row/col count vs width/hight for via array size
        specs('use_array_size', 'no', 'Via count based on array size', ChoiceConstraint(['yes', 'no']))
        specs('vn_total_width',  '0.7u', 'Via array total width')
        specs('vn_total_height', '0.62u', 'Via array total height')

    def setupParams(self, params):
        # process parameter values entered by user
        self.params = params
        self.b_layer = params['b_layer']
        self.t_layer = params['t_layer']
        self.vn_columns = params['vn_columns']
        self.vn_rows = params['vn_rows']
        ## UPDATE: Process new parameters
        self.extra_vias = params['extra_vias'] == 'yes'
        self.use_array_size = params['use_array_size'] == 'yes'
        if self.use_array_size:
            self.vn_total_width =Numeric(params['vn_total_width'])*1e6
            self.vn_total_height = Numeric(params['vn_total_height'])*1e6  
        else:
            self.vn_total_width = 0
            self.vn_total_height = 0      
    
    
    def genLayout(self):

        b_layer = self.b_layer
        t_layer = self.t_layer

        self.techparams = self.tech.getTechParams()
        self.epsilon = self.techparams['epsilon1']
        self.grid = self.tech.getGridResolution()         # needed for Dogbone
        
        offset_x = self.sx if hasattr(self, 'sx') and self.sx is not None else 0
        offset_y = self.sy if hasattr(self, 'sy') and self.sy is not None else 0
        
        self.extra_vias = False if not hasattr(self, 'extra_vias') else self.extra_vias


        Cell = self.__class__.__name__

        textlayer = 'TEXT'

        #*************************************************************************
        #*
        #* Generic Design Rule Definitions
        #*
        #************************************************************************

        epsilon = techparams['epsilon1']
        ## UPDATE: Parameters for the Gat/Activ contacts/metal1
        cont_size = self.techparams['Cnt_a']
        cont_enc1 = self.techparams['Cnt_c']
        cont_enc2 = self.techparams['M1_c1']
        cont_enc3 = self.techparams['M1_c']
        cont_sep1 = self.techparams['Cnt_b']
        cont_sep2 = self.techparams['Cnt_b1']
        ##
        v1_size = techparams['V1_a']
        v1_sep1 = techparams['V1_b']
        v1_sep2 = techparams['V1_b1']
        v1_enc = techparams['V1_c1']
        ## UPDATE: Enc1 for top/bottom enclosure
        v1_enc1 = techparams['V1_c']

        vn_size = techparams['Vn_a']
        vn_sep1 = techparams['Vn_b']
        vn_sep2 = techparams['Vn_b1']
        vn_enc = techparams['Vn_c1']
        ## UPDATE: Enc1 for top/bottom enclosure
        vn_enc1 = techparams['Vn_c']

        # TopVia1 parameters for M4-TM1 connection
        # TopVia1 is larger than regular vias (0.42um vs 0.19um)
        tv1_size = techparams.get('TV1_a', 0.42)  # TopVia1 size
        tv1_sep = techparams.get('TV1_b', 0.42)   # TopVia1 spacing
        tv1_enc = techparams.get('TV1_c', 0.10)   # Metal4 enclosure of TopVia1
        tm1_enc = techparams.get('TV1_d', 0.42)   # TopMetal1 enclosure of TopVia1
        tm1_min_width = techparams.get('TM1_a', 1.64)  # Minimum width of TopMetal1 when connecting to M4 with TopVia1
        
        
        # UPDATE: Minimum metal area rule
        mn_metal_area = techparams.get('Mn_d', 0.144)  # Minimum metal area (if applicable)
        #*************************************************************************
        #*
        #* Device Specific Design Rule Definitions
        #*
        #************************************************************************

        ## UPDATE: process via array size parameters
        vn_columns = self.vn_columns
        vn_rows = self.vn_rows
        
        ## UPDATE: added to avoid parameter errors when use the via_class in other pcells
        vn_total_width = self.vn_total_width if hasattr(self, 'vn_total_width') else 0
        vn_total_height = self.vn_total_height if hasattr(self, 'vn_total_height') else 0

        # SG13CMOS5L: M1-M4-TM1 metal stack (TopVia1 connects M4 to TopMetal1)
        metal_layers = ['Metal1', 'Metal2', 'Metal3', 'Metal4', 'TopMetal1']
        via_layers = ['Via1', 'Via2', 'Via3', 'TopVia1']
        
        #*************************************************************************
        #*
        #* Main body of code
        #*
        #************************************************************************
        
        ## UPDATE: Process Activ/Poly layers
        ## DESCRIPTION: Cannot add directly the GatPoly/Activ layers to the metal array
        ## If we do that, the stacked masks will be: Gat - Activ - M1 ..
        ## but the bottom mask can be either Gat or Activ than directly connect to M1,
        ## to let the same Metal process and include the Gat/Activ, we will
        ## add the Gat/Activ layer only if it is the bottom layer
        ## else the stack still starts from M1
        if self.b_layer in ['GatPoly', 'Activ']:
            metal_layers.insert(0,self.b_layer)
            via_layers.insert(0, 'Cont')
        idx_b = metal_layers.index(b_layer)
        idx_t = metal_layers.index(t_layer)
        if idx_b > idx_t:
            idx_b, idx_t = idx_t, idx_b
            b_layer, t_layer = t_layer, b_layer  # Also swap layer names
        stack_layers = metal_layers[idx_b:idx_t+1]
        
        ## UPDATE: A routine to process the via array col/rows based on col/row params or width/height params.
        def via_count_from_size(via_size, via_sep, via_total_size, via_num):
            ## We use the total size only if it is greater than 0, otherwise we fall back to the via_num specified by the user
            ret = math.floor((via_total_size + via_sep)/(via_size + via_sep)) if via_total_size > 0 else via_num
            ## Thats a special case, i used it in one of my pcells,
            ## sometimes i need the via size to not exceed the total size
            ## so i set the col/row number to 0 to decrease the total size (and insure that the  array size is always <= total_size)
            ## to avoid DRC errors
            return max(ret-1 if via_num == 0 else ret, 1)

        ## UPDATE: To fill the space under the bigger vias with small vias
        ## we can just use the already implemented via_array_size, so the script
        ## will automatically calculate the required via number to fill the area under the bigger vias
        if vn_total_width == 0 and self.extra_vias:
            ## default via array size
            via_size = vn_size
            via_sep = vn_sep2
            via_enc = vn_enc1
            ## starting from the bigger vias
            if t_layer == 'TopMetal1':
                via_size = tv1_size
                via_sep = tv1_sep
                via_enc = tm1_enc
            ## smaller vias special case
            elif t_layer == 'Metal1':
                via_size = cont_size
                via_sep = cont_sep2
                via_enc = cont_enc2
            vn_total_width = (vn_columns * via_size + (vn_columns - 1) * via_sep) + via_enc
            vn_total_height = (vn_rows * via_size + (vn_rows - 1) * via_sep) + via_enc
        
        ## UPDATE: Use the previouse defined routine to calculate the required
        ## via count on each layer
        cont_cols_from_size = via_count_from_size(cont_size, cont_sep2, vn_total_width - cont_enc1*2, vn_columns)
        cont_rows_from_size = via_count_from_size(cont_size, cont_sep2, vn_total_height, vn_rows)
        v1_cols_from_size = via_count_from_size(v1_size, v1_sep2, vn_total_width, vn_columns)
        v1_rows_from_size = via_count_from_size(v1_size, v1_sep2, vn_total_height, vn_rows)
        vn_cols_from_size = via_count_from_size(vn_size, vn_sep2, vn_total_width, vn_columns)
        vn_rows_from_size = via_count_from_size(vn_size, vn_sep2, vn_total_height, vn_rows)
        tv1_cols_from_size = via_count_from_size(tv1_size, tv1_sep, vn_total_width, vn_columns)
        tv1_rows_from_size = via_count_from_size(tv1_size, tv1_sep, vn_total_height, vn_rows)

        for layer in stack_layers:
            ## TODO:
            ## The via sep here is use the sep1 if cols and rows less than 4
            ## but we need to separate the cols and rows
            ## via_sep_cols for the cols use the sep1 if cols less than 4 else sep2
            ## via_sep_rows for the rows use the sep1 if rows less than 4 else
            via_enc1 = None
            #pre-procesing
            ## UPDATE: Process the new added layers Activ/GatPoly using the same metal process
            if layer in ['Activ', 'GatPoly']:
                columns = cont_cols_from_size
                rows = cont_rows_from_size
                via_size = cont_size
                via_enc = cont_enc1
                via_sep = cont_sep1 if (columns<4 and rows<4) else cont_sep2
                w_x = (columns * via_size + (columns - 1) * via_sep)
                w_y = (rows * via_size + (rows - 1) * via_sep)
                via_array_w_x = w_x
                via_array_w_y = w_y
            ## UPDATE: Metal1 was not a top metal before, now it needs a special process
            elif t_layer == 'Metal1':
                columns = cont_cols_from_size
                rows = cont_rows_from_size
                via_size = cont_size
                via_sep = cont_sep1 if (columns<4 and rows<4) else cont_sep2
                via_enc = cont_enc2
                via_enc1 = cont_enc3
                w_x = (columns * via_size + (columns - 1) * via_sep)
                w_y = (rows * via_size + (rows - 1) * via_sep)
                via_array_w_x = w_x
                via_array_w_y = w_y
            elif layer == 'Metal1':
                columns = v1_cols_from_size
                rows = v1_rows_from_size
                via_size = v1_size
                via_sep = v1_sep1 if (columns<4 and rows<4) else v1_sep2
                via_enc = v1_enc
                via_enc1 = v1_enc1
                w_x = (columns * via_size + (columns - 1) * via_sep)
                w_y = (rows * via_size + (rows - 1) * via_sep)
                via_array_w_x = w_x
                via_array_w_y = w_y

            elif layer == 'TopMetal1':  # TopMetal1 uses TopVia1 (larger vias)
                columns = tv1_cols_from_size
                rows = tv1_rows_from_size
                via_size = tv1_size
                via_sep = tv1_sep
                via_enc = tm1_enc  # TopMetal1 enclosure of TopVia1
                w_x = (columns * via_size + (columns - 1) * via_sep)
                w_y = (rows * via_size + (rows - 1) * via_sep)
                via_array_w_x = w_x
                via_array_w_y = w_y

            elif layer == 'Metal4' and 'TopMetal1' in stack_layers:
                # Metal4 connected to TopMetal1: M4 area must match TM1 area
                columns = vn_cols_from_size
                rows = vn_rows_from_size
                # Via3 parameters (for drawing Via3 - keep original size)
                via_size = vn_size
                via_sep = vn_sep1 if (columns<4 and rows<4) else vn_sep2
                via_enc = tm1_enc  # Use TM1 enclosure so M4 rect = TM1 rect
                # Via3 array size (for positioning Via3)
                via_array_w_x = (columns * via_size + (columns - 1) * via_sep)
                via_array_w_y = (rows * via_size + (rows - 1) * via_sep)
                # Metal4 rectangle uses TopVia1 params (matches TM1 area)
                w_x = (tv1_cols_from_size * tv1_size + (tv1_cols_from_size - 1) * tv1_sep)
                w_y = (tv1_rows_from_size * tv1_size + (tv1_rows_from_size - 1) * tv1_sep)

            else:  # Metal2, Metal3, or Metal4 without TopMetal1
                columns = vn_cols_from_size
                rows = vn_rows_from_size
                via_size = vn_size
                via_sep = vn_sep1 if (columns<4 and rows<4) else vn_sep2
                via_enc = vn_enc
                via_enc1 = vn_enc1
                w_x = (columns * via_size + (columns - 1) * via_sep)
                w_y = (rows * via_size + (rows - 1) * via_sep)
                via_array_w_x = w_x
                via_array_w_y = w_y
            via_enc1 = via_enc if via_enc1 == None else via_enc1
            
            ## UPDATE: Processing the metal box size based on the new param width/height
            box_w = w_x/2 + via_enc 
            box_h = w_y/2 + via_enc1 
            if layer in ['Activ', 'GatPoly'] :
                if vn_total_width != 0:
                    box_w = max(box_w, vn_total_width/2)
                if vn_total_height != 0:
                    box_h = max(vn_total_height/2, box_h)
            ## UPDATE: Respect the minimum width/height for TopMetal1 to avoid DRC errors
            if layer == 'TopMetal1':
                box_w = max(box_w, tm1_min_width/2)  # Ensure minimum width for TopMetal1
                box_h = max(box_h, tm1_min_width/2)  # Ensure minimum height for TopMetal1
            
            ## UPDATE: Respect the minimum metal area rule by increasing the smaller dimension if the area is less than the minimum
            ## TODO: Clean this part    
            area = 4*box_w*box_h
            if area < mn_metal_area:
                max_dim = max(box_w, box_h)*2
                new_dim = area/max_dim/2
                box_w = new_dim + 0.005 if box_w <= box_h else box_w
                box_h = new_dim + 0.005 if box_h < box_w else box_h
            
            ## UPDATE: Snap to grid, to avoid DRC offgrid errors
            box_w = GridFix(box_w)
            box_h = GridFix(box_h)
    
            metal_box = Box(-box_w + offset_x, -box_h + offset_y, box_w + offset_x, box_h + offset_y)
            
            #metal draw
            dbCreateRect(self, layer, metal_box)
            ## UPDATE: Special case for Metal1, reset parameters to use the contact parameters since it can be connected to either Activ/GatPoly or Metal2
            if layer == 'Metal1':
                columns = cont_cols_from_size
                rows = cont_rows_from_size
                via_size = cont_size
                via_sep = cont_sep1 if (columns<4 and rows<4) else cont_sep2
                via_enc = cont_enc2
                via_enc1 = cont_enc3
                w_x = (columns * via_size + (columns - 1) * via_sep)
                w_y = (rows * via_size + (rows - 1) * via_sep)
                via_array_w_x = w_x
                via_array_w_y = w_y
            
            #via draw
            if layer != b_layer:
                via_layer = via_layers[metal_layers.index(layer)-1]
                for i in range(columns):
                    ## UPDATE: Adding an offset, make me drow the via array at any position on the parent cell
                    ## if i need to use the via_stack class in other pcells.
                    x0 = i * via_sep + i * via_size - via_array_w_x/2 + offset_x
                    for j in range(rows):
                        y0 = j * via_sep + j * via_size - via_array_w_y/2 + offset_y
                        dbCreateRect(self, via_layer, Box(x0, y0, x0 + via_size, y0 + via_size))
