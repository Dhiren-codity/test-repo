module Spaceship
  class ConnectAPI
    module Model
      def self.included(base)
        base.extend(ClassMethods)
      end

      module ClassMethods
        def attr_mapping(mapping = nil)
          if mapping.nil?
            return @attr_mapping ||= {}
          end

          @attr_mapping = mapping
          attr_accessor(*mapping.values.map(&:to_sym))
          return @attr_mapping
        end

        def type
          return self.name.split('::').last
        end

        def parse(client, attrs)
          model = self.new(client)

          if attrs.kind_of?(Hash)
            model.id = attrs["id"]
            model.type = attrs["type"] || self.type

            data = attrs["attributes"] || {}
            self.attr_mapping.each do |api_name, accessor_name|
              next unless data.key?(api_name)
              model.public_send("#{accessor_name}=", data[api_name])
            end
          end

          return model
        end
      end

      attr_accessor :client
      attr_accessor :id
      attr_accessor :type

      def initialize(client = nil)
        @client = client
      end

      def reverse_attr_mapping(attributes)
        mapping = self.class.attr_mapping
        inverted_mapping = mapping.each_with_object({}) do |(api_name, accessor_name), hash|
          hash[accessor_name.to_s] = api_name
        end

        return_hash = {}
        attributes.each do |key, value|
          key_string = key.to_s
          return_hash[inverted_mapping[key_string] || key_string] = value
        end

        return return_hash
      end
    end
  end
end
