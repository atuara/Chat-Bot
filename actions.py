from __future__ import absolute_import
from __future__ import division
from __future__ import unicode_literals

import logging
import json
import smtplib

from email.message import EmailMessage
##from rasa.constants import DEFAULT_DATA_PATH
from rasa.shared.constants import (
    DEFAULT_DATA_PATH,
    DEFAULT_CONFIG_PATH,
    DEFAULT_DOMAIN_PATH,
    DOCS_URL_MIGRATION_GUIDE,
)
from rasa_sdk import Action, Tracker
from rasa_sdk.events import AllSlotsReset, SlotSet, Restarted

from zomato.zomato_api import Zomato

import warnings
warnings.filterwarnings("ignore")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("__name__")
user_key = "810872d4d561674a6f2d22162b7b2efb"
config = {"user_key": user_key}
api_zomato = Zomato(config)


## Custom action that is used to fetch list of restaurants

class ActionSearchRestaurants(Action):
    def name(self):
        return "action_restaurant"

    def run(self, dispatcher, tracker, domain):

        response_message = ""
        email_message = ""
        search_validity = "valid"

        budget = tracker.get_slot("budget")
        location = tracker.get_slot("location")
        cuisine = tracker.get_slot("cuisine")

        
        if not location:
            search_validity = "invalid"
        else:
            """
				retrieve location details
			"""
            response = api_zomato.get_location(location)
            location_details = {}

            if response is not None:
                response_json = json.loads(response)
                if response_json["status"] == "success":
                    """
						fetch location details and store 'city_id'
					"""
                    location_details = response_json["location_suggestions"][0]
                    city_id = location_details["city_id"]
                    city_name = location_details["city_name"]

                    """
                        Validate if the location details is of the requested location
                    """
                    if location.lower() == city_name.lower():

                        """
                            fetch all cuisines available in the location
                        """
                        response_cuisine = api_zomato.get_cuisines(city_id)
                        supported_cuisines_names = [
                            "American",
                            "Chinese",
                            "Italian",
                            "Mexican",
                            "North Indian",
                            "South Indian",
                        ]
                        """ 
                            filter only supported cuisines
                        """
                        filtered_cuisine = {
                            key: value
                            for key, value in response_cuisine.items()
                            if value in supported_cuisines_names
                        }

                        if cuisine is not None:
                            cuisine_list = [
                                key
                                for key, value in filtered_cuisine.items()
                                if str(value).lower() == cuisine.lower()
                            ]
                        else:
                            cuisine_list = [
                                key for key, value in filtered_cuisine.items()
                            ]

                        restaurants_found = self.search_restaurant(
                            location, location_details, cuisine_list
                        )

                        if len(restaurants_found) > 0:
                            restaurant_filtered_budget = self.filter_restaurant_by_budget(budget, restaurants_found)
                            number_of_records = 10

                            if len(restaurant_filtered_budget) < 10:
                                number_of_records = len(restaurant_filtered_budget)

                            for indx in range(0, number_of_records):
                                restaurant = restaurant_filtered_budget[indx]
                                if indx < 5:
                                    response_message = (
                                        response_message
                                        + "\n   "
                                        + str(indx + 1)
                                        + ". "
                                        + restaurant["name"]
                                        + " in "
                                        + restaurant["address"] 
                                        + " has been rated "
                                        + restaurant["rating"]
                                        + " out of 5"
                                        + "\n"
                                    )

                                email_message = (
                                    email_message
                                    + "\n   "
                                    + str(indx + 1)
                                    + ". "
                                    + restaurant["name"]
                                    + " in "
                                    + restaurant["address"] 
                                    + " has been rated "
                                    + restaurant["rating"]
                                    + " out of 5. "
                                    + "Average cost for 2 : "
                                    + str(restaurant["avg_cost_for_2"])
                                    + "\n"
                                )

                        else:
                            search_validity = "invalid"
                    else:
                        search_validity = "invalid"
                else:
                    search_validity = "invalid"                            
            else:
                search_validity = "invalid"

        if search_validity == "valid":
            dispatcher.utter_message(response_message)

        return [SlotSet("search_validity", search_validity), SlotSet("email_message", email_message)]

    def search_restaurant(
        self, location="", location_details={}, cuisine_list=[]
    ) -> list:
        restaurants_found = []

        """
			Search restaurants
		"""
        response = api_zomato.restaurant_search(
            location,
            location_details["latitude"],
            location_details["longitude"],
            cuisine_list,
            location_details["city_id"],
            "city",
            100
        )

        if response is not None:
            response_json = json.loads(response)
            if response_json["results_found"] > 0:
                for restaurant in response_json["restaurants"]:
                    restaurants_found.append(
                        {
                            "name": restaurant["restaurant"]["name"],
                            "address": restaurant["restaurant"]["location"]["address"],
                            "avg_cost_for_2": restaurant["restaurant"]["average_cost_for_two"],
                            "rating": restaurant["restaurant"]["user_rating"]["aggregate_rating"],
                        }
                    )

        return restaurants_found

    def filter_restaurant_by_budget(self, budget, restaurant_list) -> list:
        filtered_restaurant_list = []

        """
            Set the budget range based on input
        """
        rangeMin = 0
        rangeMax = 999999
       
        if budget == "299":
            rangeMax = 299
        elif budget == "700":
            rangeMin = 300
            rangeMax = 700
        elif budget == "701":
            rangeMin = 701
        else:
            """
                Default budget
            """
            rangeMin = 0
            rangeMax = 9999

        for restaurant in restaurant_list:
            avg_cost = int(restaurant["avg_cost_for_2"])

            if avg_cost >= rangeMin and avg_cost <= rangeMax:
                filtered_restaurant_list.append(restaurant)

        return filtered_restaurant_list


## Custom action to check user input location

class ActionValidateLocation(Action):
    def name(self):
        return "action_location_valid"

    def run(self, dispatcher, tracker, domain):

        location = tracker.get_slot("location")
        location_validity = "valid"

        if not location:
            location_validity = "invalid"
        else:
            filepath = DEFAULT_DATA_PATH + "/cities_list.json"

            with open(filepath) as cities_file:

                data = json.load(cities_file)

                if data is not None:
                    tier1_cities_names = data["data"]["tier1"]
                    tier2_cities_names = data["data"]["tier2"]

                    tier1_cities_lowercase = [city.lower() for city in tier1_cities_names]
                    tier2_cities_lowercase = [city.lower() for city in tier2_cities_names]

                    location_validity = (
                        "invalid"
                        if location.lower() not in tier1_cities_lowercase
                        and location.lower() not in tier2_cities_lowercase
                        else "valid"
                    )
                else:
                    location_validity = "invalid"

        return [SlotSet("location_validity", location_validity)]


## Custom action to validate input cuisine

class ActionValidateCuisine(Action):
    def name(self):
        return "action_cuisine_valid"

    def run(self, dispatcher, tracker, domain):

        cuisine = tracker.get_slot("cuisine")
        cuisine_check = "valid"

        if not cuisine:
            cuisine_check = "invalid"
        else:
            supported_cuisines_names = ["american","chinese","italian","mexican","north indian","south indian"]

            cuisine_check = (
                "invalid" if cuisine.lower() not in supported_cuisines_names else "valid")

        return [SlotSet("cuisine_validity", cuisine_check)]


class ActionRestarted(Action): 	
	def name(self):
		return 'action_restart'

	def run(self, dispatcher, tracker, domain):
		return[Restarted()] 


class ActionSlotReset(Action): 
	def name(self): 
		return 'action_slot_reset' 

	def run(self, dispatcher, tracker, domain): 
		return[AllSlotsReset()]


## Defined  action to send  mail

class ActionSendEmail(Action):

    def name(self):
        return "action_send_email"

    def run(self, dispatcher, tracker, domain):

        location = tracker.get_slot("location")
        cuisine = tracker.get_slot("cuisine")
        email_id = tracker.get_slot("email")
        email_message = tracker.get_slot("email_message")
        
        """
            Parse email id
            Required to handle email id sent from SLACK connector
        """
        str_email_id = str(email_id)
        if str_email_id.startswith("mailto"):
            separator_index = str_email_id.index("|")
            if separator_index > -1:
                emails = str_email_id.split("|")
                email_id = emails[1]

        """
            Create an email message
        """
        msg = EmailMessage()

        msg.set_content(email_message)
        msg['Subject'] = "Foodie restaurant Bot | List of {0} Restaurants in {1}".format(cuisine, location)

        """
            Read SMTP configuration
        """
        smtp_config = {}
        filepath = DEFAULT_DATA_PATH + "/smtpconfiguration.txt"
        print(filepath)
        with open(filepath) as mail_file:
            for line in mail_file:
                name, var = line.partition("=")[::2]
                smtp_config[name.strip()] = var.strip()
		        
        """
            Send email to the user
        """
        try:
            s = smtplib.SMTP_SSL(host=smtp_config["smtpserver_host"], port=smtp_config["smtpserver_port"])
            s.login(smtp_config["username"], smtp_config["password"])
        
            msg['From'] = smtp_config["from_email"]
            msg['To'] = email_id
            print(smtp_config["smtpserver_host"])
            print(smtp_config["smtpserver_port"])
            print(smtp_config["username"])
            print(smtp_config["password"])
            s.send_message(msg)
            s.quit()
        except Exception as exception:
            print("failed to send an email, please look in to the problem ")
            print(exception)

        return [AllSlotsReset()]
