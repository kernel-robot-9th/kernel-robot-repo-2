# A detected object on the table, in BlockArray.header.frame_id (link0 for one arm, world for two).
string id          # e.g. "red_0"
string color       # red | green | blue | yellow | purple ...
string kind        # block | tray (a long object carried with both arms)
float64 x          # [m]
float64 y          # [m]
float64 yaw        # block: yaw mod 90 deg in [-pi/4, pi/4); tray: long-axis yaw in [-pi/2, pi/2)
int32 u            # image pixel (centroid)
int32 v
float64 area_px
float64 length     # long side on the table [m]
float64 width      # short side [m]
