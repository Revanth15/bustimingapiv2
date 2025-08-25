from fastapi import APIRouter, HTTPException, Query
from routers.database import getDBClient
from routers.utils import queryAPI
import re
from datetime import datetime

dbClient = getDBClient()

traffic_image_router = APIRouter()

camera_id_descriptions = {
    "1111": "TPE(PIE) - Exit 2 to Loyang Ave",
    "1112": "TPE(PIE) - Tampines Viaduct",
    "1113": "Tanah Merah Coast Road towards Changi",

    "1701": "CTE (AYE) - Moulmein Flyover LP448F",
    "1702": "CTE (AYE) - Braddell Flyover LP274F",
    "1703": "CTE (SLE) - Blk 22 St George's Road",
    "1704": "CTE (AYE) - Entrance from Chin Swee Road",
    "1705": "CTE (AYE) - Ang Mo Kio Ave 5 Flyover",
    "1706": "CTE (AYE) - Yio Chu Kang Flyover",
    "1707": "CTE (AYE) - Bukit Merah Flyover",
    "1709": "CTE (AYE) - Exit 6 to Bukit Timah Road",
    "1711": "CTE (AYE) - Ang Mo Kio Flyover",

    "2701": "Woodlands Causeway (Towards Johor)",
    "2702": "Woodlands Checkpoint",
    "2703": "BKE (PIE) - Chantek F/O",
    "2704": "BKE (Woodlands Checkpoint) - Woodlands F/O",
    "2705": "BKE (PIE) - Dairy Farm F/O",
    "2706": "Entrance from Mandai Rd (Towards Checkpoint)",
    "2707": "Exit 5 to KJE (towards PIE)",
    "2708": "Exit 5 to KJE (Towards Checkpoint)",

    "3702": "ECP (Changi) - Entrance from PIE",
    "3704": "ECP (Changi) - Entrance from KPE",
    "3705": "ECP (AYE) - Exit 2A to Changi Coast Road",
    "3793": "ECP (Changi) - Laguna Flyover",
    "3795": "ECP (City) - Marine Parade F/O",
    "3796": "ECP (Changi) - Tanjong Katong F/O",
    "3797": "ECP (City) - Tanjung Rhu",
    "3798": "ECP (Changi) - Benjamin Sheares Bridge",

    "4701": "AYE (City) - Alexander Road Exit",
    "4702": "AYE (Jurong) - Keppel Viaduct",
    "4703": "Tuas Second Link",
    "4704": "AYE (CTE) - Lower Delta Road F/O",
    "4705": "AYE (MCE) - Entrance from Yuan Ching Rd",
    "4706": "AYE (Jurong) - NUS Sch of Computing TID",
    "4707": "AYE (MCE) - Entrance from Jln Ahmad Ibrahim",
    "4708": "AYE (CTE) - ITE College West Dover TID",
    "4709": "Clementi Ave 6 Entrance",
    "4710": "AYE(Tuas) - Pandan Garden",
    "4712": "AYE(Tuas) - Tuas Ave 8 Exit",
    "4713": "Tuas Checkpoint",
    "4714": "AYE (Tuas) - Near West Coast Walk",
    "4716": "AYE (Tuas) - Entrance from Benoi Rd",

    "4798": "Sentosa Tower 1",
    "4799": "Sentosa Tower 2",

    "5794": "PIEE (Jurong) - Bedok North",
    "5795": "PIEE (Jurong) - Eunos F/O",
    "5797": "PIEE (Jurong) - Paya Lebar F/O",
    "5798": "PIEE (Jurong) - Kallang Sims Drive Blk 62",
    "5799": "PIEE (Changi) - Woodsville F/O",

    "6701": "PIEW (Changi) - Blk 65A Jln Tenteram, Kim Keat",
    "6703": "PIEW (Changi) - Blk 173 Toa Payoh Lorong 1",
    "6704": "PIEW (Jurong) - Mt Pleasant F/O",
    "6705": "PIEW (Changi) - Adam F/O Special pole",
    "6706": "PIEW (Changi) - BKE",
    "6708": "Nanyang Flyover (Towards Changi)",
    "6710": "Entrance from Jln Anak Bukit (Towards Changi)",
    "6711": "Entrance from ECP (Towards Jurong)",
    "6712": "Exit 27 to Clementi Ave 6",
    "6713": "Entrance From Simei Ave (Towards Jurong)",
    "6714": "Exit 35 to KJE (Towards Changi)",
    "6715": "Hong Kah Flyover (Towards Jurong)",
    "6716": "AYE Flyover",

    "7791": "TPE (PIE) - Upper Changi F/O",
    "7793": "TPE(PIE) - Entrance to PIE from Tampines Ave 10",
    "7794": "TPE(SLE) - TPE Exit KPE",
    "7795": "TPE(PIE) - Entrance from Tampines FO",
    "7796": "TPE(SLE) - On rooftop of Blk 189A Rivervale Drive 9",
    "7797": "TPE(PIE) - Seletar Flyover",
    "7798": "TPE(SLE) - LP790F (On SLE Flyover)",

    "8701": "KJE (PIE) - Choa Chu Kang West Flyover",
    "8702": "KJE (BKE) - Exit To BKE",
    "8704": "KJE (BKE) - Entrance From Choa Chu Kang Dr",
    "8706": "KJE (BKE) - Tengah Flyover",

    "9701": "SLE (TPE) - Lentor F/O",
    "9702": "SLE(TPE) - Thomson Flyover",
    "9703": "SLE(Woodlands) - Woodlands South Flyover",
    "9704": "SLE(TPE) - Ulu Sembawang Flyover",
    "9705": "SLE(TPE) - Beside Slip Road From Woodland Ave 2",
    "9706": "SLE(Woodlands) - Mandai Lake Flyover",
}

@traffic_image_router.get("/traffic_images")
async def get_traffic_images():
    try:
        ltaResponse = await queryAPI("ltaodataservice/Traffic-Imagesv2", {})
        images = ltaResponse.get("value", [])
        if not images:
             return []
        
        processed_images = []
        for img in images:
            image_link = img.get("ImageLink", "")
            
            # Extract the date and time from the URL using regex
            match = re.search(r"/(\d{4}-\d{2}-\d{2})/(\d{2}-\d{2})/", image_link)
            if match:
                date_str, time_str = match.groups()
                
                # Convert time_str from "HH-MM" to "HH:MM"
                formatted_time = time_str.replace("-", ":")
                
                try:
                    img_datetime = datetime.strptime(f"{date_str} {formatted_time}", "%Y-%m-%d %H:%M")
                    img["ImageDate"] = img_datetime.strftime("%d/%m/%y")
                    img["ImageTime"] = img_datetime.strftime("%H:%M")
                except ValueError:
                    img["ImageDate"] = date_str
                    img["ImageTime"] = formatted_time
            else:
                img["ImageDate"] = None
                img["ImageTime"] = None

            camera_id = str(img.get("CameraID"))
            img["Description"] = camera_id_descriptions.get(camera_id, "Unknown Location")

            processed_images.append(img)

        return processed_images
    except HTTPException as he:
        raise he
    except Exception as e:
        print(f"Unexpected error: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")
    